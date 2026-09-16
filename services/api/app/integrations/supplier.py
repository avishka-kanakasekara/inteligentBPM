"""Mock SupplierProvider — quotation request drafts, send, ingest, reject."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.database.memory import get_memory_store, new_id
from app.integrations.errors import ProviderRateLimitError, ProviderTimeoutError, SupplierRejectedError
from app.integrations.protocols import QuotationRequestDraft
from app.repositories.memory_repos import SupplierContactRepository, SupplierRepository


class MockSupplierProvider:
    name = "mock_supplier"

    def __init__(
        self,
        *,
        force_timeout: bool = False,
        force_rate_limit: bool = False,
        force_reject: bool = False,
    ) -> None:
        self.force_timeout = force_timeout
        self.force_rate_limit = force_rate_limit
        self.force_reject = force_reject

    def list_approved_suppliers(self, *, organization_id: UUID) -> list[dict[str, Any]]:
        return [
            {
                "id": str(s.id),
                "name": s.name,
                "code": s.code,
                "approval_status": s.approval_status,
                "status": s.status,
            }
            for s in SupplierRepository(organization_id).list_all()
            if s.approval_status == "approved" and s.status == "active"
        ]

    def list_contacts(self, *, organization_id: UUID, supplier_id: str) -> list[dict[str, Any]]:
        sid = UUID(supplier_id)
        SupplierRepository(organization_id).get(sid)
        return [
            {
                "id": str(c.id),
                "full_name": c.full_name,
                "email": c.email,
                "status": c.status,
                "supplier_id": str(c.supplier_id),
            }
            for c in SupplierContactRepository(organization_id).list_all(supplier_id=sid)
            if c.status == "active"
        ]

    def create_quotation_request_draft(
        self,
        *,
        organization_id: UUID,
        supplier_id: str,
        product_sku: str,
        quantity: float,
        contact_email: str | None,
        idempotency_key: str,
    ) -> QuotationRequestDraft:
        store = get_memory_store()
        for existing in store.quote_requests.values():
            if (
                existing.get("organization_id") == str(organization_id)
                and existing.get("idempotency_key") == idempotency_key
            ):
                return _draft_from_record(existing)

        SupplierRepository(organization_id).get(UUID(supplier_id))
        request_id = new_id()
        subject = f"Quotation request for {product_sku}"
        body = (
            f"Please provide a quotation for SKU {product_sku}, quantity {quantity}.\n"
            f"Include unit price, currency, tax, shipping, delivery days, and warranty."
        )
        record = {
            "id": str(request_id),
            "organization_id": str(organization_id),
            "supplier_id": supplier_id,
            "contact_email": contact_email,
            "product_sku": product_sku,
            "quantity": quantity,
            "status": "draft",
            "subject": subject,
            "body": body,
            "idempotency_key": idempotency_key,
            "outbound_message_id": None,
            "mock": True,
        }
        store.quote_requests[request_id] = record
        return _draft_from_record(record)

    def send_quotation_request(
        self,
        *,
        organization_id: UUID,
        draft_id: str,
        idempotency_key: str,
        authorized: bool = False,
    ) -> QuotationRequestDraft:
        if self.force_timeout:
            raise ProviderTimeoutError("Supplier provider timed out", provider=self.name)
        if self.force_rate_limit:
            raise ProviderRateLimitError("Supplier provider rate limited", provider=self.name)
        if not authorized:
            raise PermissionError("Quotation request send requires authorization")

        store = get_memory_store()
        draft = store.quote_requests.get(UUID(draft_id))
        if draft is None or draft.get("organization_id") != str(organization_id):
            raise LookupError("Quotation request draft not found")

        if self.force_reject or draft.get("force_reject"):
            draft["status"] = "rejected"
            draft["rejection_reason"] = "Supplier declined to quote"
            raise SupplierRejectedError(
                "Supplier rejected quotation request",
                supplier_id=str(draft.get("supplier_id")),
            )

        if draft.get("status") == "sent":
            return _draft_from_record(draft)

        msg_id = str(new_id())
        draft["status"] = "sent"
        draft["outbound_message_id"] = msg_id
        draft["send_idempotency_key"] = idempotency_key
        draft["outbound_metadata"] = {
            "provider": self.name,
            "message_id": msg_id,
            "to": draft.get("contact_email"),
            "subject": draft.get("subject"),
        }
        return _draft_from_record(draft)

    def ingest_response(
        self,
        *,
        organization_id: UUID,
        request_id: str,
        raw_text: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        store = get_memory_store()
        req = store.quote_requests.get(UUID(request_id))
        if req is None or req.get("organization_id") != str(organization_id):
            raise LookupError("Quote request not found")
        if req.get("status") == "rejected":
            raise SupplierRejectedError(
                "Cannot ingest response for rejected request",
                supplier_id=str(req.get("supplier_id")),
            )

        quote_id = new_id()
        record = {
            "id": str(quote_id),
            "organization_id": str(organization_id),
            "request_id": request_id,
            "supplier_id": req["supplier_id"],
            "raw_text": raw_text,
            "idempotency_key": idempotency_key,
            "status": "ingested",
            "mock": True,
            "untrusted": True,
        }
        store.quotations[quote_id] = record
        return record

    def reject_request(
        self,
        *,
        organization_id: UUID,
        request_id: str,
        reason: str,
    ) -> dict[str, Any]:
        store = get_memory_store()
        req = store.quote_requests.get(UUID(request_id))
        if req is None or req.get("organization_id") != str(organization_id):
            raise LookupError("Quote request not found")
        req["status"] = "rejected"
        req["rejection_reason"] = reason
        return dict(req)

    # Legacy Agent 4 gateway helpers
    def request_quote(
        self,
        *,
        organization_id: UUID,
        supplier_id: str,
        product_sku: str,
        quantity: int,
        idempotency_key: str,
        subject: str | None = None,
        body: str | None = None,
        contact_email: str | None = None,
    ) -> dict[str, Any]:
        contacts = self.list_contacts(organization_id=organization_id, supplier_id=supplier_id)
        email = contact_email or (contacts[0]["email"] if contacts else None)
        draft = self.create_quotation_request_draft(
            organization_id=organization_id,
            supplier_id=supplier_id,
            product_sku=product_sku,
            quantity=float(quantity),
            contact_email=email,
            idempotency_key=idempotency_key,
        )
        _ = (subject, body)  # accepted for API parity with live provider
        sent = self.send_quotation_request(
            organization_id=organization_id,
            draft_id=draft.id,
            idempotency_key=f"{idempotency_key}:send",
            authorized=True,
        )
        return {
            "id": sent.id,
            "organization_id": str(organization_id),
            "supplier_id": supplier_id,
            "product_sku": product_sku,
            "quantity": quantity,
            "status": sent.status,
            "idempotency_key": idempotency_key,
            "mock": True,
            "outbound_message_id": sent.outbound_message_id,
        }

    def collect_quote(
        self,
        *,
        organization_id: UUID,
        request_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        store = get_memory_store()
        req = store.quote_requests.get(UUID(request_id))
        if req is None or req.get("organization_id") != str(organization_id):
            raise LookupError("Quote request not found")
        qty = float(req.get("quantity") or 1)
        unit = 100.0 + (qty % 17)
        quote_id = new_id()
        record = {
            "id": str(quote_id),
            "organization_id": str(organization_id),
            "request_id": request_id,
            "supplier_id": req["supplier_id"],
            "currency": "USD",
            "unit_price": unit,
            "quantity": qty,
            "tax": round(unit * qty * 0.08, 2),
            "shipping": 25.0,
            "delivery_days": 10,
            "warranty_months": 12,
            "payment_terms_days": 30,
            "unit": "each",
            "sku": req.get("product_sku"),
            "status": "collected",
            "idempotency_key": idempotency_key,
            "mock": True,
            "untrusted": True,
        }
        store.quotations[quote_id] = record
        return record


def _draft_from_record(record: dict[str, Any]) -> QuotationRequestDraft:
    return QuotationRequestDraft(
        id=str(record["id"]),
        organization_id=str(record["organization_id"]),
        supplier_id=str(record["supplier_id"]),
        contact_email=record.get("contact_email"),
        product_sku=str(record.get("product_sku") or ""),
        quantity=float(record.get("quantity") or 0),
        status=str(record.get("status") or "draft"),
        subject=str(record.get("subject") or ""),
        body=str(record.get("body") or ""),
        idempotency_key=record.get("idempotency_key"),
        outbound_message_id=record.get("outbound_message_id"),
        mock=bool(record.get("mock", True)),
    )


class RealSupplierProvider:
    name = "real_supplier"

    def __init__(self, *, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url

    def list_approved_suppliers(self, **kwargs: Any) -> list[dict[str, Any]]:
        raise NotImplementedError("Real supplier API not wired")

    def list_contacts(self, **kwargs: Any) -> list[dict[str, Any]]:
        raise NotImplementedError("Real supplier API not wired")

    def create_quotation_request_draft(self, **kwargs: Any) -> QuotationRequestDraft:
        raise NotImplementedError("Real supplier API not wired")

    def send_quotation_request(self, **kwargs: Any) -> QuotationRequestDraft:
        raise NotImplementedError("Real supplier API not wired")

    def ingest_response(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("Real supplier API not wired")

    def reject_request(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("Real supplier API not wired")
