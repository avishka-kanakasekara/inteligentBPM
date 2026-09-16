"""Mock PurchasingProvider — PO drafts, approval binding, submit after approval."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.database.memory import get_memory_store, new_id
from app.integrations.errors import ProviderTimeoutError
from app.integrations.protocols import PurchaseOrderDraft


class MockPurchasingProvider:
    name = "mock_purchasing"

    def __init__(self, *, force_timeout: bool = False) -> None:
        self.force_timeout = force_timeout

    def create_purchase_order_draft(
        self,
        *,
        organization_id: UUID,
        supplier_id: str,
        amount_total: float,
        currency_code: str,
        lines: list[dict[str, Any]],
        idempotency_key: str,
    ) -> PurchaseOrderDraft:
        store = get_memory_store()
        for existing in store.purchase_orders.values():
            if (
                existing.get("organization_id") == str(organization_id)
                and existing.get("idempotency_key") == idempotency_key
            ):
                return _po_from_record(existing)

        po_id = new_id()
        record = {
            "id": str(po_id),
            "organization_id": str(organization_id),
            "supplier_id": supplier_id,
            "amount_total": amount_total,
            "currency_code": currency_code,
            "lines": lines,
            "status": "draft",
            "approval_id": None,
            "idempotency_key": idempotency_key,
            "submitted": False,
            "mock": True,
        }
        store.purchase_orders[po_id] = record
        return _po_from_record(record)

    def request_approval(
        self,
        *,
        organization_id: UUID,
        purchase_order_id: str,
        approval_id: str,
    ) -> PurchaseOrderDraft:
        store = get_memory_store()
        po = store.purchase_orders.get(UUID(purchase_order_id))
        if po is None or po.get("organization_id") != str(organization_id):
            raise LookupError("Purchase order not found")
        po["approval_id"] = approval_id
        po["status"] = "pending_approval"
        return _po_from_record(po)

    def submit_purchase_order(
        self,
        *,
        organization_id: UUID,
        purchase_order_id: str,
        idempotency_key: str,
        approved: bool = False,
    ) -> PurchaseOrderDraft:
        if self.force_timeout:
            raise ProviderTimeoutError("Purchasing provider timed out", provider=self.name)

        store = get_memory_store()
        po = store.purchase_orders.get(UUID(purchase_order_id))
        if po is None or po.get("organization_id") != str(organization_id):
            raise LookupError("Purchase order not found")

        if po.get("status") == "submitted":
            return _po_from_record(po)

        if not approved and po.get("status") != "approved":
            # Require explicit approval binding
            if po.get("status") == "pending_approval" and not approved:
                raise PermissionError("Purchase order requires approval before submit")
            if po.get("status") == "draft":
                raise PermissionError("Purchase order requires approval before submit")

        po["status"] = "submitted"
        po["submitted"] = True
        po["submit_idempotency_key"] = idempotency_key
        po["external_ref"] = f"MOCK-PO-{purchase_order_id[:8]}"
        po["mock"] = True
        return _po_from_record(po)

    # Legacy gateway method names
    def create_draft(
        self,
        *,
        organization_id: UUID,
        supplier_id: str,
        amount_total: float,
        currency_code: str,
        lines: list[dict[str, Any]],
        idempotency_key: str,
    ) -> dict[str, Any]:
        draft = self.create_purchase_order_draft(
            organization_id=organization_id,
            supplier_id=supplier_id,
            amount_total=amount_total,
            currency_code=currency_code,
            lines=lines,
            idempotency_key=idempotency_key,
        )
        return {
            "id": draft.id,
            "organization_id": draft.organization_id,
            "supplier_id": draft.supplier_id,
            "amount_total": draft.amount_total,
            "currency_code": draft.currency_code,
            "lines": draft.lines,
            "status": draft.status,
            "idempotency_key": idempotency_key,
            "mock": True,
            "submitted": False,
        }

    def submit(
        self,
        *,
        organization_id: UUID,
        purchase_order_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        # Gateway already gated on approval; treat as approved for submit.
        draft = self.submit_purchase_order(
            organization_id=organization_id,
            purchase_order_id=purchase_order_id,
            idempotency_key=idempotency_key,
            approved=True,
        )
        return {
            "id": draft.id,
            "organization_id": draft.organization_id,
            "supplier_id": draft.supplier_id,
            "amount_total": draft.amount_total,
            "currency_code": draft.currency_code,
            "lines": draft.lines,
            "status": draft.status,
            "submitted": True,
            "external_ref": draft.external_ref,
            "mock": True,
            "submit_idempotency_key": idempotency_key,
        }


def _po_from_record(record: dict[str, Any]) -> PurchaseOrderDraft:
    return PurchaseOrderDraft(
        id=str(record["id"]),
        organization_id=str(record["organization_id"]),
        supplier_id=str(record["supplier_id"]),
        amount_total=float(record.get("amount_total") or 0),
        currency_code=str(record.get("currency_code") or "USD"),
        lines=list(record.get("lines") or []),
        status=str(record.get("status") or "draft"),
        approval_id=record.get("approval_id"),
        external_ref=record.get("external_ref"),
        mock=bool(record.get("mock", True)),
    )


class RealPurchasingProvider:
    name = "real_purchasing"

    def __init__(self, *, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url

    def create_purchase_order_draft(self, **kwargs: Any) -> PurchaseOrderDraft:
        raise NotImplementedError("Real purchasing API not wired")

    def request_approval(self, **kwargs: Any) -> PurchaseOrderDraft:
        raise NotImplementedError("Real purchasing API not wired")

    def submit_purchase_order(self, **kwargs: Any) -> PurchaseOrderDraft:
        raise NotImplementedError("Real purchasing API not wired")
