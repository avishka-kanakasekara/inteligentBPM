"""Integration adapters — provider interfaces, mocks, credentials, quotation workflow."""

from app.integrations.credentials import ProviderCredentialStore, SecretVault
from app.integrations.errors import (
    DuplicateSendError,
    InvalidRecipientError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    SupplierRejectedError,
)
from app.integrations.factory import ProviderBundle, build_providers
from app.integrations.protocols import (
    BillingProvider,
    CalendarProvider,
    EmailProvider,
    IdentityProvider,
    PurchasingProvider,
    SupplierProvider,
)
from app.integrations.quotation_workflow import SupplierQuotationWorkflow
from app.integrations.storage import StorageIntegration

__all__ = [
    "BillingProvider",
    "CalendarProvider",
    "DuplicateSendError",
    "EmailProvider",
    "IdentityProvider",
    "InvalidRecipientError",
    "ProviderBundle",
    "ProviderCredentialStore",
    "ProviderError",
    "ProviderNotConfiguredError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "PurchasingProvider",
    "SecretVault",
    "StorageIntegration",
    "SupplierProvider",
    "SupplierQuotationWorkflow",
    "SupplierRejectedError",
    "build_providers",
]
