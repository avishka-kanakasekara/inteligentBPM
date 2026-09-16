"""Provider factory — selects mock vs real implementations without coupling the engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.config import Settings, get_settings
from app.integrations.billing import (
    MockBillingProvider,
    MockCalendarProvider,
    MockIdentityProvider,
    RealBillingProvider,
)
from app.integrations.credentials import ProviderCredentialStore
from app.integrations.email import MockEmailProvider, RealEmailProvider
from app.integrations.errors import ProviderNotConfiguredError
from app.integrations.protocols import (
    BillingProvider,
    CalendarProvider,
    EmailProvider,
    IdentityProvider,
    PurchasingProvider,
    SupplierProvider,
)
from app.integrations.purchasing import MockPurchasingProvider, RealPurchasingProvider
from app.integrations.supplier import MockSupplierProvider, RealSupplierProvider


@dataclass
class ProviderBundle:
    email: EmailProvider
    calendar: CalendarProvider
    supplier: SupplierProvider
    purchasing: PurchasingProvider
    identity: IdentityProvider
    billing: BillingProvider
    mode: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "email": self.email.name,
            "calendar": self.calendar.name,
            "supplier": self.supplier.name,
            "purchasing": self.purchasing.name,
            "identity": self.identity.name,
            "billing": self.billing.name,
            "mode": self.mode,
        }


def _env_or_vault_secret(
    *,
    organization_id: UUID | None,
    provider: str,
    env_value: str | None,
    store: ProviderCredentialStore,
) -> str | None:
    if env_value:
        return env_value
    if organization_id is not None:
        return store.get_secret(organization_id=organization_id, provider=provider)
    return None


def build_providers(
    *,
    settings: Settings | None = None,
    organization_id: UUID | None = None,
    force_mock: bool | None = None,
    email_kwargs: dict[str, Any] | None = None,
    supplier_kwargs: dict[str, Any] | None = None,
    purchasing_kwargs: dict[str, Any] | None = None,
) -> ProviderBundle:
    """
    Resolve providers for the process engine.

    Real providers are constructed only when credentials exist (env or encrypted vault).
    Otherwise mocks are used — never couples the engine to a single vendor.
    """
    cfg = settings or get_settings()
    mode = getattr(cfg, "integrations_mode", "mock") or "mock"
    if force_mock is True or mode == "mock":
        return ProviderBundle(
            email=MockEmailProvider(**(email_kwargs or {})),
            calendar=MockCalendarProvider(),
            supplier=MockSupplierProvider(**(supplier_kwargs or {})),
            purchasing=MockPurchasingProvider(**(purchasing_kwargs or {})),
            identity=MockIdentityProvider(),
            billing=MockBillingProvider(),
            mode="mock",
        )

    vault = ProviderCredentialStore()
    email_key = _env_or_vault_secret(
        organization_id=organization_id,
        provider="email",
        env_value=getattr(cfg, "email_api_key", None),
        store=vault,
    )
    supplier_key = _env_or_vault_secret(
        organization_id=organization_id,
        provider="supplier",
        env_value=getattr(cfg, "supplier_api_key", None),
        store=vault,
    )
    purchasing_key = _env_or_vault_secret(
        organization_id=organization_id,
        provider="purchasing",
        env_value=getattr(cfg, "purchasing_api_key", None),
        store=vault,
    )
    billing_key = _env_or_vault_secret(
        organization_id=organization_id,
        provider="billing",
        env_value=getattr(cfg, "billing_api_key", None),
        store=vault,
    )

    email: EmailProvider
    from_addr = getattr(cfg, "email_from_address", None)
    smtp_host = getattr(cfg, "email_smtp_host", None)
    provider_name = (getattr(cfg, "email_provider", None) or "").lower()
    if from_addr and (email_key or smtp_host):
        # brevo/sendgrid/mailgun SMTP keys still use the SMTP transport path
        smtp_providers = {"smtp", "brevo", "sendinblue", "sendgrid", "mailgun", "ses"}
        if provider_name in smtp_providers or smtp_host:
            transport = "smtp"
        elif provider_name == "resend" or (email_key and not smtp_host):
            transport = "resend"
        else:
            transport = provider_name or "smtp"
        email = RealEmailProvider(
            api_key=email_key,
            from_address=from_addr,
            provider=transport,
            smtp_host=smtp_host,
            smtp_port=int(getattr(cfg, "email_smtp_port", 587) or 587),
            smtp_username=getattr(cfg, "email_smtp_username", None),
            smtp_password=getattr(cfg, "email_smtp_password", None) or email_key,
            smtp_use_tls=bool(getattr(cfg, "email_smtp_use_tls", True)),
        )
    else:
        email = MockEmailProvider(**(email_kwargs or {}))

    supplier: SupplierProvider
    if supplier_key and getattr(cfg, "supplier_api_base_url", None):
        supplier = RealSupplierProvider(
            api_key=supplier_key,
            base_url=cfg.supplier_api_base_url or "",
        )
    else:
        supplier = MockSupplierProvider(**(supplier_kwargs or {}))

    purchasing: PurchasingProvider
    if purchasing_key and getattr(cfg, "purchasing_api_base_url", None):
        purchasing = RealPurchasingProvider(
            api_key=purchasing_key,
            base_url=cfg.purchasing_api_base_url or "",
        )
    else:
        purchasing = MockPurchasingProvider(**(purchasing_kwargs or {}))

    billing: BillingProvider
    if billing_key and getattr(cfg, "billing_api_base_url", None):
        billing = RealBillingProvider(
            api_key=billing_key,
            base_url=cfg.billing_api_base_url or "",
        )
    else:
        billing = MockBillingProvider()

    return ProviderBundle(
        email=email,
        calendar=MockCalendarProvider(),
        supplier=supplier,
        purchasing=purchasing,
        identity=MockIdentityProvider(),
        billing=billing,
        mode="auto",
    )


def require_real_provider(provider_name: str, bundle: ProviderBundle) -> None:
    """Raise if a real provider was expected but mock is still bound."""
    mapping = {
        "email": bundle.email.name,
        "supplier": bundle.supplier.name,
        "purchasing": bundle.purchasing.name,
        "billing": bundle.billing.name,
    }
    name = mapping.get(provider_name)
    if name is None or name.startswith("mock_"):
        raise ProviderNotConfiguredError(provider_name)
