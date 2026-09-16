"""Encrypted provider credential vault — never store raw secrets in normal DB columns."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from app.contracts.common import utcnow
from app.database.memory import get_memory_store


ALG = "HMAC-SHA256-CTR-v1"
DEFAULT_KEY_ID = "local-dev-v1"


def _derive_key(master_secret: str, key_id: str) -> bytes:
    return hashlib.sha256(f"{key_id}:{master_secret}".encode()).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, stream, strict=True))


@dataclass(frozen=True)
class SealedSecret:
    """Opaque sealed payload suitable for persistence (no plaintext)."""

    ciphertext_b64: str
    nonce_b64: str
    key_id: str
    alg: str = ALG

    def to_record(self) -> dict[str, str]:
        return {
            "ciphertext_b64": self.ciphertext_b64,
            "nonce_b64": self.nonce_b64,
            "key_id": self.key_id,
            "alg": self.alg,
        }

    @classmethod
    def from_record(cls, data: dict[str, Any]) -> SealedSecret:
        return cls(
            ciphertext_b64=str(data["ciphertext_b64"]),
            nonce_b64=str(data["nonce_b64"]),
            key_id=str(data["key_id"]),
            alg=str(data.get("alg") or ALG),
        )


class SecretVault:
    """
    Managed secret store abstraction.

    Seals/opens secrets with a process-local master key (APP_SIGNING_SECRET or
    INTEGRATIONS_SECRET_KEY). Only ciphertext + metadata is persisted.
    """

    def __init__(self, master_secret: str | None = None, *, key_id: str = DEFAULT_KEY_ID) -> None:
        from app.config import get_settings

        settings = get_settings()
        secret = (
            master_secret
            or getattr(settings, "integrations_secret_key", None)
            or getattr(settings, "app_signing_secret", None)
            or os.environ.get("INTEGRATIONS_SECRET_KEY")
            or os.environ.get("APP_SIGNING_SECRET")
            or "dev-only-integrations-secret-not-for-production"
        )
        self._master = secret
        self.key_id = key_id

    def seal(self, plaintext: str) -> SealedSecret:
        key = _derive_key(self._master, self.key_id)
        nonce = secrets.token_bytes(16)
        raw = plaintext.encode("utf-8")
        cipher = _xor(raw, _keystream(key, nonce, len(raw)))
        return SealedSecret(
            ciphertext_b64=base64.urlsafe_b64encode(cipher).decode("ascii"),
            nonce_b64=base64.urlsafe_b64encode(nonce).decode("ascii"),
            key_id=self.key_id,
            alg=ALG,
        )

    def open(self, sealed: SealedSecret | dict[str, Any]) -> str:
        if isinstance(sealed, dict):
            sealed = SealedSecret.from_record(sealed)
        if sealed.alg != ALG:
            raise ValueError(f"Unsupported secret algorithm: {sealed.alg}")
        key = _derive_key(self._master, sealed.key_id)
        cipher = base64.urlsafe_b64decode(sealed.ciphertext_b64.encode("ascii"))
        nonce = base64.urlsafe_b64decode(sealed.nonce_b64.encode("ascii"))
        plain = _xor(cipher, _keystream(key, nonce, len(cipher)))
        return plain.decode("utf-8")


class ProviderCredentialStore:
    """Persist encrypted provider credentials (ciphertext only)."""

    def __init__(self, vault: SecretVault | None = None) -> None:
        self.vault = vault or SecretVault()

    def put(
        self,
        *,
        organization_id: UUID,
        provider: str,
        secret_value: str,
        label: str | None = None,
    ) -> UUID:
        sealed = self.vault.seal(secret_value)
        store = get_memory_store()
        cred_id = uuid4()
        # Strip any accidental plaintext fields — only sealed payload is stored.
        store.encrypted_credentials[cred_id] = {
            "id": str(cred_id),
            "organization_id": str(organization_id),
            "provider": provider,
            "label": label,
            "sealed": sealed.to_record(),
            "created_at": utcnow().isoformat(),
            # Explicitly never store: api_key, password, token, secret
        }
        return cred_id

    def get_secret(self, *, organization_id: UUID, provider: str) -> str | None:
        store = get_memory_store()
        for record in store.encrypted_credentials.values():
            if (
                record.get("organization_id") == str(organization_id)
                and record.get("provider") == provider
            ):
                sealed = record.get("sealed")
                if not sealed:
                    return None
                return self.vault.open(sealed)
        return None

    def has_credentials(self, *, organization_id: UUID, provider: str) -> bool:
        return self.get_secret(organization_id=organization_id, provider=provider) is not None

    def delete(self, *, organization_id: UUID, provider: str) -> int:
        store = get_memory_store()
        to_delete = [
            cid
            for cid, record in store.encrypted_credentials.items()
            if record.get("organization_id") == str(organization_id)
            and record.get("provider") == provider
        ]
        for cid in to_delete:
            del store.encrypted_credentials[cid]
        return len(to_delete)
