"""Integration provider errors — engine stays decoupled from vendor-specific failures."""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for all integration provider failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "provider_error",
        retryable: bool = False,
        provider: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.provider = provider


class ProviderNotConfiguredError(ProviderError):
    def __init__(self, provider: str, message: str | None = None) -> None:
        super().__init__(
            message or f"Real {provider} provider requires credentials; using mock until configured",
            code="provider_not_configured",
            retryable=False,
            provider=provider,
        )


class ProviderTimeoutError(ProviderError):
    def __init__(self, message: str = "Provider timed out", *, provider: str | None = None) -> None:
        super().__init__(message, code="provider_timeout", retryable=True, provider=provider)


class ProviderRateLimitError(ProviderError):
    def __init__(
        self,
        message: str = "Provider rate limit exceeded",
        *,
        provider: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message, code="provider_rate_limit", retryable=True, provider=provider)
        self.retry_after_seconds = retry_after_seconds


class InvalidRecipientError(ProviderError):
    def __init__(self, message: str, *, recipients: list[str] | None = None) -> None:
        super().__init__(message, code="invalid_recipient", retryable=False, provider="email")
        self.recipients = recipients or []


class DuplicateSendError(ProviderError):
    def __init__(self, message: str = "Duplicate send prevented", *, idempotency_key: str | None = None) -> None:
        super().__init__(message, code="duplicate_send", retryable=False, provider="email")
        self.idempotency_key = idempotency_key


class SupplierRejectedError(ProviderError):
    def __init__(self, message: str = "Supplier rejected quotation request", *, supplier_id: str | None = None) -> None:
        super().__init__(message, code="supplier_rejected", retryable=False, provider="supplier")
        self.supplier_id = supplier_id
