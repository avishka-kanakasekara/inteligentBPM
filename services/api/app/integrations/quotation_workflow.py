"""Supplier quotation workflow — orchestrates providers without binding to one vendor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from app.agents.execution.quotations import (
    compare_quotations,
    extract_quotation_from_text,
    normalize_quotation,
)
from app.database.memory import get_memory_store, new_id
from app.domain.enums import ApprovalStatus
from app.integrations.factory import ProviderBundle, build_providers


LOW_CONFIDENCE_THRESHOLD = 0.55


@dataclass
class QuotationWorkflowResult:
    organization_id: UUID
    process_run_id: UUID | None
    steps: list[dict[str, Any]] = field(default_factory=list)
    drafts: list[dict[str, Any]] = field(default_factory=list)
    quotations: list[dict[str, Any]] = field(default_factory=list)
    comparison: dict[str, Any] | None = None
    recommendation: dict[str, Any] | None = None
    purchase_order: dict[str, Any] | None = None
    approval_id: UUID | None = None
    status: str = "in_progress"
    clarification_needed: list[dict[str, Any]] = field(default_factory=list)


class SupplierQuotationWorkflow:
    """
    End-to-end quotation workflow:

    1 approved suppliers → 2 contacts → 3 drafts → 4 show drafts →
    5 send (authorized) → 6 store outbound metadata → 7 ingest →
    8 extract → 9 clarify if low confidence → 10 normalize →
    11 compare → 12 recommend → 13 PO draft → 14 approval → 15 submit
    """

    def __init__(self, providers: ProviderBundle | None = None) -> None:
        self.providers = providers or build_providers(force_mock=True)

    def _step(self, result: QuotationWorkflowResult, name: str, **detail: Any) -> None:
        result.steps.append({"step": name, **detail})

    def run(
        self,
        *,
        organization_id: UUID,
        product_sku: str,
        quantity: float,
        process_run_id: UUID | None = None,
        authorized_to_send: bool = False,
        show_drafts: bool = True,
        response_texts: dict[str, str] | None = None,
        approval_id: UUID | None = None,
        submit_after_approval: bool = False,
        idempotency_prefix: str | None = None,
    ) -> QuotationWorkflowResult:
        prefix = idempotency_prefix or f"quote-{uuid4()}"
        result = QuotationWorkflowResult(
            organization_id=organization_id,
            process_run_id=process_run_id,
        )

        # 1. Retrieve approved suppliers
        suppliers = self.providers.supplier.list_approved_suppliers(
            organization_id=organization_id
        )
        self._step(result, "retrieve_approved_suppliers", count=len(suppliers))
        if not suppliers:
            result.status = "blocked_no_suppliers"
            return result

        # 2–6 per supplier
        for idx, supplier in enumerate(suppliers):
            sid = str(supplier["id"])
            contacts = self.providers.supplier.list_contacts(
                organization_id=organization_id, supplier_id=sid
            )
            self._step(result, "retrieve_supplier_contacts", supplier_id=sid, count=len(contacts))
            contact_email = contacts[0]["email"] if contacts else None

            draft = self.providers.supplier.create_quotation_request_draft(
                organization_id=organization_id,
                supplier_id=sid,
                product_sku=product_sku,
                quantity=quantity,
                contact_email=contact_email,
                idempotency_key=f"{prefix}:draft:{idx}",
            )
            draft_dict = {
                "id": draft.id,
                "supplier_id": draft.supplier_id,
                "contact_email": draft.contact_email,
                "subject": draft.subject,
                "body": draft.body,
                "status": draft.status,
            }
            result.drafts.append(draft_dict)
            self._step(result, "create_quotation_request_draft", draft_id=draft.id)

            # 4. Show drafts when required
            if show_drafts:
                self._step(result, "show_draft", draft=draft_dict)

            # 5–6. Send after authorization + store outbound metadata
            if authorized_to_send:
                sent = self.providers.supplier.send_quotation_request(
                    organization_id=organization_id,
                    draft_id=draft.id,
                    idempotency_key=f"{prefix}:send:{idx}",
                    authorized=True,
                )
                draft_dict["status"] = sent.status
                draft_dict["outbound_message_id"] = sent.outbound_message_id
                self._step(
                    result,
                    "send_quotation_request",
                    draft_id=sent.id,
                    outbound_message_id=sent.outbound_message_id,
                )
                self._step(
                    result,
                    "store_outbound_metadata",
                    outbound_message_id=sent.outbound_message_id,
                    supplier_id=sid,
                )

                # Optional: also record via email provider for thread tracking
                if contact_email:
                    msg = self.providers.email.send_email(
                        organization_id=organization_id,
                        to=[contact_email],
                        subject=draft.subject,
                        body=draft.body,
                        idempotency_key=f"{prefix}:email:{idx}",
                    )
                    self._step(
                        result,
                        "email_outbound",
                        provider_message_id=msg.provider_message_id,
                        thread_id=msg.thread_id,
                    )

        if not authorized_to_send:
            result.status = "awaiting_authorization"
            return result

        # 7–9. Ingest responses, extract, clarify
        texts = response_texts or {}
        extracted_raw: list[dict[str, Any]] = []
        for draft in result.drafts:
            sid = draft["supplier_id"]
            raw = texts.get(sid) or texts.get(draft["id"])
            if not raw:
                # Synthetic deterministic response for mock path when none provided
                raw = (
                    f"Quote from supplier {sid}: unit price $120 USD qty {quantity} "
                    f"tax $9.60 shipping $15 delivery 7 days warranty 24 months each"
                )
            ingested = self.providers.supplier.ingest_response(
                organization_id=organization_id,
                request_id=draft["id"],
                raw_text=raw,
                idempotency_key=f"{prefix}:ingest:{sid}",
            )
            self._step(result, "ingest_response", quotation_id=ingested["id"], request_id=draft["id"])

            extracted = extract_quotation_from_text(raw, supplier_id=sid)
            confidence = _extraction_confidence(extracted)
            extracted["confidence"] = confidence
            extracted["id"] = ingested["id"]
            extracted["quotation_id"] = ingested["id"]
            try:
                from app.observability.metrics import M_QUOTE_CONFIDENCE, metrics

                metrics.observe(M_QUOTE_CONFIDENCE, confidence * 1000.0)
            except Exception:  # noqa: BLE001
                pass

            # Persist extracted fields onto quotation record
            store = get_memory_store()
            qrec = store.quotations.get(UUID(ingested["id"]))
            if qrec:
                qrec.update({k: v for k, v in extracted.items() if k != "id"})

            self._step(result, "extract_quote_fields", quotation_id=ingested["id"], confidence=confidence)

            if confidence < LOW_CONFIDENCE_THRESHOLD:
                missing = _missing_quote_fields(extracted)
                result.clarification_needed.append(
                    {
                        "quotation_id": ingested["id"],
                        "supplier_id": sid,
                        "missing_fields": missing,
                        "confidence": confidence,
                    }
                )
                self._step(
                    result,
                    "request_clarification",
                    quotation_id=ingested["id"],
                    missing_fields=missing,
                )
            extracted_raw.append(extracted)
            result.quotations.append(extracted)

        if result.clarification_needed and not all(
            q.get("confidence", 0) >= LOW_CONFIDENCE_THRESHOLD for q in extracted_raw
        ):
            # Continue with available quotes but mark clarification
            result.status = "clarification_requested"

        # 10. Normalize
        normalized = [normalize_quotation(q) for q in extracted_raw]
        self._step(result, "normalize_quotes", count=len(normalized))

        # 11. Compare deterministically
        comparison = compare_quotations(normalized)
        result.comparison = comparison.model_dump(mode="json")
        self._step(
            result,
            "compare_quotes",
            winner=comparison.winner_quotation_id,
            ranking=comparison.ranking,
        )

        # 12. Recommendation with evidence
        winner = next(
            (q for q in normalized if q.quotation_id == comparison.winner_quotation_id),
            None,
        )
        result.recommendation = {
            "winner_quotation_id": comparison.winner_quotation_id,
            "supplier_id": winner.supplier_id if winner else None,
            "total_cost_usd": winner.total_cost_usd if winner else None,
            "evidence": {
                "scores": {k: v.model_dump() for k, v in comparison.scores.items()},
                "explanation": comparison.explanation,
                "deterministic": True,
            },
        }
        self._step(result, "generate_recommendation", recommendation=result.recommendation)

        if winner is None:
            result.status = "no_winner"
            return result

        # 13. Create purchase order draft
        po = self.providers.purchasing.create_purchase_order_draft(
            organization_id=organization_id,
            supplier_id=winner.supplier_id,
            amount_total=winner.total_cost_usd,
            currency_code="USD",
            lines=[
                {
                    "sku": product_sku,
                    "quantity": quantity,
                    "unit_price": winner.subtotal_usd / quantity if quantity else 0,
                }
            ],
            idempotency_key=f"{prefix}:po",
        )
        result.purchase_order = {
            "id": po.id,
            "supplier_id": po.supplier_id,
            "amount_total": po.amount_total,
            "currency_code": po.currency_code,
            "status": po.status,
        }
        self._step(result, "create_purchase_order_draft", purchase_order_id=po.id)

        # 14. Request approval
        approval = approval_id or new_id()
        # Bind approval record if not provided
        store = get_memory_store()
        if approval_id is None:
            from app.database.memory import ApprovalRecord
            from app.contracts.common import utcnow

            now = utcnow()
            store.approvals[approval] = ApprovalRecord(
                id=approval,
                organization_id=organization_id,
                process_run_id=process_run_id,
                status=ApprovalStatus.PENDING,
                snapshot_hash=f"po:{po.id}",
                snapshot_payload={"purchase_order_id": po.id, "amount": po.amount_total},
                decided_by_user_id=None,
                decision_note=None,
                row_version=1,
                created_at=now,
                updated_at=now,
            )
        po_pending = self.providers.purchasing.request_approval(
            organization_id=organization_id,
            purchase_order_id=po.id,
            approval_id=str(approval),
        )
        result.approval_id = approval
        result.purchase_order["status"] = po_pending.status
        result.purchase_order["approval_id"] = str(approval)
        self._step(result, "request_approval", approval_id=str(approval))

        # 15. Submit after approval
        approval_rec = store.approvals.get(approval)
        is_approved = bool(approval_rec and approval_rec.status == ApprovalStatus.APPROVED)

        if submit_after_approval:
            if not is_approved:
                result.status = "awaiting_po_approval"
                return result
            submitted = self.providers.purchasing.submit_purchase_order(
                organization_id=organization_id,
                purchase_order_id=po.id,
                idempotency_key=f"{prefix}:po-submit",
                approved=True,
            )
            result.purchase_order["status"] = submitted.status
            result.purchase_order["external_ref"] = submitted.external_ref
            self._step(result, "submit_purchase_order", purchase_order_id=po.id)
            result.status = "completed"
        else:
            result.status = (
                "awaiting_po_approval"
                if not is_approved
                else "po_approved_ready"
            )

        return result

    def approve_and_submit_po(
        self,
        *,
        organization_id: UUID,
        purchase_order_id: str,
        approval_id: UUID,
        decided_by_user_id: UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        store = get_memory_store()
        approval = store.approvals.get(approval_id)
        if approval is None or approval.organization_id != organization_id:
            raise LookupError("Approval not found")
        from app.contracts.common import utcnow

        approval.status = ApprovalStatus.APPROVED
        approval.decided_by_user_id = decided_by_user_id
        approval.decision = "approved"
        approval.decision_timestamp = utcnow()
        approval.updated_at = utcnow()

        submitted = self.providers.purchasing.submit_purchase_order(
            organization_id=organization_id,
            purchase_order_id=purchase_order_id,
            idempotency_key=idempotency_key,
            approved=True,
        )
        return {
            "purchase_order_id": submitted.id,
            "status": submitted.status,
            "external_ref": submitted.external_ref,
            "approval_id": str(approval_id),
        }


def _extraction_confidence(extracted: dict[str, Any]) -> float:
    score = 0.0
    weights = {
        "unit_price": 0.35,
        "currency": 0.15,
        "quantity": 0.15,
        "tax": 0.1,
        "shipping": 0.1,
        "delivery_days": 0.1,
        "warranty_months": 0.05,
    }
    if extracted.get("unit_price"):
        score += weights["unit_price"]
    if extracted.get("currency"):
        score += weights["currency"]
    if extracted.get("quantity"):
        score += weights["quantity"]
    if extracted.get("tax"):
        score += weights["tax"]
    if extracted.get("shipping"):
        score += weights["shipping"]
    if extracted.get("delivery_days") is not None:
        score += weights["delivery_days"]
    if extracted.get("warranty_months") is not None:
        score += weights["warranty_months"]
    return round(score, 4)


def _missing_quote_fields(extracted: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not extracted.get("unit_price"):
        missing.append("unit_price")
    if not extracted.get("currency"):
        missing.append("currency")
    if extracted.get("tax") in (None, 0) and "tax" not in (extracted.get("raw_text") or ""):
        # zero tax may be valid; only flag when price missing context
        pass
    if extracted.get("delivery_days") is None:
        missing.append("delivery_days")
    if extracted.get("warranty_months") is None:
        missing.append("warranty_months")
    return missing
