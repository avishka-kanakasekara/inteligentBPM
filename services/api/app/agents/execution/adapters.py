"""Compatibility adapters for Agent 4 gateway — wrap provider interfaces.

Prefer app.integrations.factory.build_providers for new code. These classes keep
existing ToolGateway call sites working while the process engine stays decoupled
from any single vendor.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.config import get_settings
from app.integrations.email import MockEmailProvider
from app.integrations.errors import ProviderError
from app.integrations.factory import build_providers
from app.integrations.live_tools import (
    LiveCalendarAdapter,
    LiveDocumentAdapter,
    LiveNotificationAdapter,
    LivePurchasingProvider,
    LiveSupplierProvider,
    LiveTaskAdapter,
)
from app.integrations.protocols import EmailProvider
from app.integrations.purchasing import MockPurchasingProvider
from app.integrations.supplier import MockSupplierProvider
from app.repositories.memory_repos import EmployeeRepository, SupplierContactRepository

# Re-export provider failure alias used by gateway
ProviderFailure = ProviderError


def _resolve_recipient_email(organization_id: UUID, to_employee_id: str) -> str:
    """Accept employee UUID, supplier contact UUID, or raw email address."""
    raw = (to_employee_id or "").strip()
    if "@" in raw:
        return raw
    try:
        emp = EmployeeRepository(organization_id).get(UUID(raw))
        return emp.email
    except Exception:
        pass
    try:
        for contact in SupplierContactRepository(organization_id).list_all():
            if str(contact.id) == raw and contact.email:
                return contact.email
    except Exception:
        pass
    return f"{raw}@employees.local"


class EmailAdapter:
    """Gateway façade over any EmailProvider (mock or real)."""

    def __init__(self, provider: EmailProvider | None = None) -> None:
        self.provider = provider or MockEmailProvider()

    @property
    def is_mock(self) -> bool:
        return bool(getattr(self.provider, "name", "").startswith("mock_"))

    def create_draft(
        self,
        *,
        organization_id: UUID,
        to_employee_id: str,
        subject: str,
        body: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        email = _resolve_recipient_email(organization_id, to_employee_id)
        msg = self.provider.create_draft(
            organization_id=organization_id,
            to=[email],
            subject=subject,
            body=body,
            idempotency_key=idempotency_key,
        )
        return {
            "id": msg.id,
            "organization_id": msg.organization_id,
            "to_employee_id": to_employee_id,
            "to": msg.to,
            "subject": msg.subject,
            "body": msg.body,
            "status": msg.status,
            "idempotency_key": msg.idempotency_key,
            "thread_id": msg.thread_id,
            "provider_message_id": msg.provider_message_id,
            "provider": msg.provider,
            "mock": msg.mock,
            "created_at": msg.created_at,
        }

    def send(
        self,
        *,
        organization_id: UUID,
        to_employee_id: str,
        subject: str,
        body: str,
        idempotency_key: str,
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        email = _resolve_recipient_email(organization_id, to_employee_id)
        msg = self.provider.send_email(
            organization_id=organization_id,
            to=[email],
            subject=subject,
            body=body,
            idempotency_key=idempotency_key,
            draft_id=draft_id,
        )
        return {
            "id": msg.id,
            "organization_id": msg.organization_id,
            "to_employee_id": to_employee_id,
            "to": msg.to,
            "subject": msg.subject,
            "body": msg.body,
            "status": msg.status,
            "idempotency_key": msg.idempotency_key,
            "thread_id": msg.thread_id,
            "provider_message_id": msg.provider_message_id,
            "provider": msg.provider,
            "mock": msg.mock,
            "created_at": msg.created_at,
        }


MockEmailAdapter = EmailAdapter


class MockSupplierAdapter:
    def __init__(self, provider: Any | None = None) -> None:
        self.provider = provider or MockSupplierProvider()

    def request_quote(self, **kwargs: Any) -> dict[str, Any]:
        return self.provider.request_quote(**kwargs)

    def collect_quote(self, **kwargs: Any) -> dict[str, Any]:
        return self.provider.collect_quote(**kwargs)


class MockPurchasingAdapter:
    def __init__(self, provider: Any | None = None) -> None:
        self.provider = provider or MockPurchasingProvider()

    def create_draft(self, **kwargs: Any) -> dict[str, Any]:
        return self.provider.create_draft(**kwargs)

    def submit(self, **kwargs: Any) -> dict[str, Any]:
        return self.provider.submit(**kwargs)


class MockNotificationAdapter:
    def __init__(self, provider: LiveNotificationAdapter | None = None) -> None:
        self.provider = provider

    def send(
        self,
        *,
        organization_id: UUID,
        user_id: str | None,
        title: str,
        body: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if self.provider is not None:
            return self.provider.send(
                organization_id=organization_id,
                user_id=user_id,
                title=title,
                body=body,
                idempotency_key=idempotency_key,
            )
        from app.database.memory import get_memory_store, new_id

        nid = new_id()
        record = {
            "id": str(nid),
            "organization_id": str(organization_id),
            "user_id": user_id,
            "title": title,
            "body": body,
            "status": "sent",
            "idempotency_key": idempotency_key,
            "mock": True,
        }
        get_memory_store().notifications[nid] = record
        return record


def adapters_from_bundle() -> tuple[
    EmailAdapter,
    MockSupplierAdapter,
    MockPurchasingAdapter,
    MockNotificationAdapter,
    LiveCalendarAdapter,
    LiveTaskAdapter,
    LiveDocumentAdapter,
]:
    bundle = build_providers()
    email_provider = bundle.email
    email = EmailAdapter(email_provider)
    settings = get_settings()
    live = (getattr(settings, "integrations_mode", "mock") or "mock") != "mock" or not isinstance(
        email_provider, MockEmailProvider
    )
    use_live_side_effects = live or getattr(email_provider, "name", "").startswith("real_")

    # Calendar/task/document/notification always go through live adapters so Agent 4
    # persists real records; outbound mail uses whatever EmailProvider is configured.
    calendar = LiveCalendarAdapter(email=email_provider)
    tasks = LiveTaskAdapter(email=email_provider)
    documents = LiveDocumentAdapter()
    notifications = MockNotificationAdapter(LiveNotificationAdapter(email=email_provider))

    if use_live_side_effects:
        supplier = MockSupplierAdapter(LiveSupplierProvider(email=email_provider))
        purchasing = MockPurchasingAdapter(LivePurchasingProvider(email=email_provider))
    else:
        supplier = MockSupplierAdapter(
            bundle.supplier
            if isinstance(bundle.supplier, MockSupplierProvider)
            else MockSupplierProvider()
        )
        purchasing = MockPurchasingAdapter(
            bundle.purchasing
            if isinstance(bundle.purchasing, MockPurchasingProvider)
            else MockPurchasingProvider()
        )
    return email, supplier, purchasing, notifications, calendar, tasks, documents
