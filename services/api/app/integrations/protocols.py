"""Provider interfaces — process engine depends only on these protocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@dataclass
class EmailAttachment:
    filename: str
    content_type: str
    content_b64: str
    size_bytes: int | None = None


@dataclass
class EmailMessage:
    id: str
    organization_id: str
    to: list[str]
    subject: str
    body: str
    status: str  # draft | queued | sent | delivered | failed | bounced
    provider: str
    provider_message_id: str | None = None
    thread_id: str | None = None
    idempotency_key: str | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str | None = None
    mock: bool = True
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class CalendarEvent:
    id: str
    organization_id: str
    title: str
    start_at: str
    end_at: str
    attendees: list[str] = field(default_factory=list)
    status: str = "confirmed"
    provider: str = "mock"
    mock: bool = True


@dataclass
class QuotationRequestDraft:
    id: str
    organization_id: str
    supplier_id: str
    contact_email: str | None
    product_sku: str
    quantity: float
    status: str  # draft | authorized | sent | rejected
    subject: str
    body: str
    idempotency_key: str | None = None
    outbound_message_id: str | None = None
    mock: bool = True


@dataclass
class PurchaseOrderDraft:
    id: str
    organization_id: str
    supplier_id: str
    amount_total: float
    currency_code: str
    lines: list[dict[str, Any]]
    status: str  # draft | pending_approval | approved | submitted | rejected
    approval_id: str | None = None
    external_ref: str | None = None
    mock: bool = True


@dataclass
class BillingUsageEvent:
    id: str
    organization_id: str
    meter: str
    quantity: float
    status: str = "recorded"
    mock: bool = True


@runtime_checkable
class EmailProvider(Protocol):
    name: str

    def validate_recipients(self, recipients: list[str]) -> list[str]:
        """Return normalized valid recipients; raise InvalidRecipientError if any invalid."""
        ...

    def create_draft(
        self,
        *,
        organization_id: UUID,
        to: list[str],
        subject: str,
        body: str,
        idempotency_key: str,
        attachments: list[EmailAttachment] | None = None,
        thread_id: str | None = None,
    ) -> EmailMessage: ...

    def send_email(
        self,
        *,
        organization_id: UUID,
        to: list[str],
        subject: str,
        body: str,
        idempotency_key: str,
        draft_id: str | None = None,
        attachments: list[EmailAttachment] | None = None,
        thread_id: str | None = None,
    ) -> EmailMessage: ...

    def get_message(self, *, organization_id: UUID, message_id: str) -> EmailMessage | None: ...

    def get_thread(self, *, organization_id: UUID, thread_id: str) -> list[EmailMessage]: ...

    def get_delivery_status(self, *, organization_id: UUID, message_id: str) -> str: ...


@runtime_checkable
class CalendarProvider(Protocol):
    name: str

    def create_event(
        self,
        *,
        organization_id: UUID,
        title: str,
        start_at: str,
        end_at: str,
        attendees: list[str],
        idempotency_key: str,
    ) -> CalendarEvent: ...

    def get_event(self, *, organization_id: UUID, event_id: str) -> CalendarEvent | None: ...


@runtime_checkable
class SupplierProvider(Protocol):
    name: str

    def list_approved_suppliers(self, *, organization_id: UUID) -> list[dict[str, Any]]: ...

    def list_contacts(self, *, organization_id: UUID, supplier_id: str) -> list[dict[str, Any]]: ...

    def create_quotation_request_draft(
        self,
        *,
        organization_id: UUID,
        supplier_id: str,
        product_sku: str,
        quantity: float,
        contact_email: str | None,
        idempotency_key: str,
    ) -> QuotationRequestDraft: ...

    def send_quotation_request(
        self,
        *,
        organization_id: UUID,
        draft_id: str,
        idempotency_key: str,
        authorized: bool = False,
    ) -> QuotationRequestDraft: ...

    def ingest_response(
        self,
        *,
        organization_id: UUID,
        request_id: str,
        raw_text: str,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def reject_request(
        self,
        *,
        organization_id: UUID,
        request_id: str,
        reason: str,
    ) -> dict[str, Any]: ...


@runtime_checkable
class PurchasingProvider(Protocol):
    name: str

    def create_purchase_order_draft(
        self,
        *,
        organization_id: UUID,
        supplier_id: str,
        amount_total: float,
        currency_code: str,
        lines: list[dict[str, Any]],
        idempotency_key: str,
    ) -> PurchaseOrderDraft: ...

    def request_approval(
        self,
        *,
        organization_id: UUID,
        purchase_order_id: str,
        approval_id: str,
    ) -> PurchaseOrderDraft: ...

    def submit_purchase_order(
        self,
        *,
        organization_id: UUID,
        purchase_order_id: str,
        idempotency_key: str,
        approved: bool = False,
    ) -> PurchaseOrderDraft: ...


@runtime_checkable
class IdentityProvider(Protocol):
    name: str

    def resolve_user(self, *, organization_id: UUID, user_id: str) -> dict[str, Any] | None: ...

    def list_memberships(self, *, organization_id: UUID) -> list[dict[str, Any]]: ...


@runtime_checkable
class BillingProvider(Protocol):
    name: str

    def record_usage(
        self,
        *,
        organization_id: UUID,
        meter: str,
        quantity: float,
        idempotency_key: str,
    ) -> BillingUsageEvent: ...

    def get_entitlements(self, *, organization_id: UUID, plan_code: str) -> dict[str, Any]: ...
