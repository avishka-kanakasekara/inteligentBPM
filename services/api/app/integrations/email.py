"""Email providers — mock outbox + real SMTP / Resend delivery."""

from __future__ import annotations

import json
import re
import smtplib
import ssl
from email.message import EmailMessage as StdEmailMessage
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import UUID, uuid4

from app.contracts.common import utcnow
from app.database.memory import get_memory_store, new_id
from app.integrations.errors import (
    DuplicateSendError,
    InvalidRecipientError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from app.integrations.protocols import EmailAttachment, EmailMessage

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _msg_from_record(record: dict[str, Any]) -> EmailMessage:
    return EmailMessage(
        id=str(record["id"]),
        organization_id=str(record["organization_id"]),
        to=list(record.get("to") or []),
        subject=str(record.get("subject") or ""),
        body=str(record.get("body") or ""),
        status=str(record.get("status") or "draft"),
        provider=str(record.get("provider") or "mock_email"),
        provider_message_id=record.get("provider_message_id"),
        thread_id=record.get("thread_id"),
        idempotency_key=record.get("idempotency_key"),
        attachments=list(record.get("attachments") or []),
        failure_reason=record.get("failure_reason"),
        mock=bool(record.get("mock", True)),
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
    )


def validate_email_recipients(recipients: list[str]) -> list[str]:
    if not recipients:
        raise InvalidRecipientError("At least one recipient is required", recipients=[])
    normalized: list[str] = []
    invalid: list[str] = []
    for raw in recipients:
        addr = (raw or "").strip()
        if not addr or not EMAIL_RE.match(addr):
            invalid.append(raw)
        else:
            normalized.append(addr.lower())
    if invalid:
        raise InvalidRecipientError(
            f"Invalid email recipients: {', '.join(invalid)}",
            recipients=invalid,
        )
    return normalized


class MockEmailProvider:
    name = "mock_email"

    def __init__(
        self,
        *,
        force_timeout: bool = False,
        force_rate_limit: bool = False,
        auto_deliver: bool = False,
    ) -> None:
        self.force_timeout = force_timeout
        self.force_rate_limit = force_rate_limit
        self.auto_deliver = auto_deliver

    def validate_recipients(self, recipients: list[str]) -> list[str]:
        return validate_email_recipients(recipients)

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
    ) -> EmailMessage:
        validated = self.validate_recipients(to)
        store = get_memory_store()
        for existing in store.email_outbox.values():
            if (
                existing.get("organization_id") == str(organization_id)
                and existing.get("idempotency_key") == idempotency_key
                and existing.get("status") == "draft"
            ):
                return _msg_from_record(existing)

        draft_id = new_id()
        tid = thread_id or str(uuid4())
        now = utcnow().isoformat()
        att = [
            {
                "filename": a.filename,
                "content_type": a.content_type,
                "content_b64": a.content_b64,
                "size_bytes": a.size_bytes or len(a.content_b64),
            }
            for a in (attachments or [])
        ]
        record = {
            "id": str(draft_id),
            "organization_id": str(organization_id),
            "to": validated,
            "subject": subject,
            "body": body,
            "status": "draft",
            "provider": self.name,
            "provider_message_id": None,
            "thread_id": tid,
            "idempotency_key": idempotency_key,
            "attachments": att,
            "mock": True,
            "created_at": now,
            "updated_at": now,
        }
        store.email_outbox[draft_id] = record
        store.email_threads.setdefault(tid, []).append(str(draft_id))
        return _msg_from_record(record)

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
    ) -> EmailMessage:
        if self.force_timeout:
            raise ProviderTimeoutError("Mock email provider timed out", provider=self.name)
        if self.force_rate_limit:
            raise ProviderRateLimitError(
                "Mock email provider rate limited",
                provider=self.name,
                retry_after_seconds=1.0,
            )

        validated = self.validate_recipients(to)
        store = get_memory_store()

        for existing in store.email_outbox.values():
            if (
                existing.get("organization_id") == str(organization_id)
                and existing.get("idempotency_key") == idempotency_key
                and existing.get("status") in {"sent", "delivered"}
            ):
                return _msg_from_record(existing)

        now = utcnow().isoformat()
        msg_id = UUID(draft_id) if draft_id else new_id()
        existing_draft = store.email_outbox.get(msg_id) if draft_id else None
        tid = (
            thread_id
            or (existing_draft.get("thread_id") if existing_draft else None)
            or str(uuid4())
        )
        provider_message_id = f"mock-msg-{msg_id}"
        att = [
            {
                "filename": a.filename,
                "content_type": a.content_type,
                "content_b64": a.content_b64,
                "size_bytes": a.size_bytes or len(a.content_b64),
            }
            for a in (attachments or [])
        ]
        if existing_draft and existing_draft.get("attachments") and not att:
            att = list(existing_draft["attachments"])

        status = "delivered" if self.auto_deliver else "sent"
        record = {
            "id": str(msg_id),
            "organization_id": str(organization_id),
            "to": validated,
            "subject": subject,
            "body": body,
            "status": status,
            "provider": self.name,
            "provider_message_id": provider_message_id,
            "thread_id": tid,
            "idempotency_key": idempotency_key,
            "attachments": att,
            "failure_reason": None,
            "mock": True,
            "created_at": (existing_draft or {}).get("created_at") or now,
            "updated_at": now,
            "to_employee_id": validated[0] if validated else None,
        }
        store.email_outbox[msg_id] = record
        thread_list = store.email_threads.setdefault(tid, [])
        if str(msg_id) not in thread_list:
            thread_list.append(str(msg_id))
        return _msg_from_record(record)

    def get_message(self, *, organization_id: UUID, message_id: str) -> EmailMessage | None:
        store = get_memory_store()
        record = store.email_outbox.get(UUID(message_id))
        if record is None or record.get("organization_id") != str(organization_id):
            return None
        return _msg_from_record(record)

    def get_thread(self, *, organization_id: UUID, thread_id: str) -> list[EmailMessage]:
        store = get_memory_store()
        ids = store.email_threads.get(thread_id) or []
        messages: list[EmailMessage] = []
        for mid in ids:
            msg = self.get_message(organization_id=organization_id, message_id=mid)
            if msg:
                messages.append(msg)
        return messages

    def get_delivery_status(self, *, organization_id: UUID, message_id: str) -> str:
        msg = self.get_message(organization_id=organization_id, message_id=message_id)
        if msg is None:
            raise LookupError("Message not found")
        return msg.status

    def mark_failed(
        self, *, organization_id: UUID, message_id: str, reason: str
    ) -> EmailMessage:
        store = get_memory_store()
        record = store.email_outbox.get(UUID(message_id))
        if record is None or record.get("organization_id") != str(organization_id):
            raise LookupError("Message not found")
        record["status"] = "failed"
        record["failure_reason"] = reason
        record["updated_at"] = utcnow().isoformat()
        return _msg_from_record(record)


class RealEmailProvider:
    """
    Real email delivery via SMTP or Resend HTTP API.

    Always persists to the org outbox so Agent 4 can show what was sent.
    """

    name = "real_email"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        from_address: str,
        provider: str = "smtp",
        smtp_host: str | None = None,
        smtp_port: int = 587,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        smtp_use_tls: bool = True,
        resend_base_url: str = "https://api.resend.com",
    ) -> None:
        self.api_key = api_key
        self.from_address = from_address
        self.provider = (provider or "smtp").lower()
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username or api_key
        self.smtp_password = smtp_password or api_key
        self.smtp_use_tls = smtp_use_tls
        self.resend_base_url = resend_base_url.rstrip("/")
        self._outbox = MockEmailProvider(auto_deliver=False)

    def validate_recipients(self, recipients: list[str]) -> list[str]:
        return validate_email_recipients(recipients)

    def create_draft(self, **kwargs: Any) -> EmailMessage:
        msg = self._outbox.create_draft(**kwargs)
        # Mark as prepared by real provider path
        store = get_memory_store()
        record = store.email_outbox.get(UUID(msg.id))
        if record:
            record["provider"] = self.name
            record["mock"] = False
            record["transport"] = self.provider
        return self.get_message(organization_id=UUID(msg.organization_id), message_id=msg.id) or msg

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
    ) -> EmailMessage:
        validated = self.validate_recipients(to)
        # Persist first (idempotent), then deliver
        draft = self._outbox.send_email(
            organization_id=organization_id,
            to=validated,
            subject=subject,
            body=body,
            idempotency_key=idempotency_key,
            draft_id=draft_id,
            attachments=attachments,
            thread_id=thread_id,
        )
        store = get_memory_store()
        record = store.email_outbox.get(UUID(draft.id))
        if record is None:
            raise ProviderError("Failed to persist email before send", provider=self.name)

        if record.get("provider_message_id") and not str(
            record.get("provider_message_id")
        ).startswith("mock-"):
            record["mock"] = False
            record["provider"] = self.name
            return _msg_from_record(record)

        try:
            if self.provider == "resend":
                provider_message_id = self._send_resend(
                    to=validated, subject=subject, body=body
                )
            else:
                provider_message_id = self._send_smtp(
                    to=validated, subject=subject, body=body
                )
        except Exception as exc:  # noqa: BLE001
            record["status"] = "failed"
            record["failure_reason"] = str(exc)
            record["provider"] = self.name
            record["mock"] = False
            record["updated_at"] = utcnow().isoformat()
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(str(exc), provider=self.name, retryable=True) from exc

        record["status"] = "sent"
        record["provider"] = self.name
        record["provider_message_id"] = provider_message_id
        record["mock"] = False
        record["transport"] = self.provider
        record["failure_reason"] = None
        record["updated_at"] = utcnow().isoformat()
        return _msg_from_record(record)

    def _send_smtp(self, *, to: list[str], subject: str, body: str) -> str:
        if not self.smtp_host:
            raise ProviderError(
                "SMTP host not configured (EMAIL_SMTP_HOST)",
                provider=self.name,
                retryable=False,
            )
        msg = StdEmailMessage()
        msg["From"] = self.from_address
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg.set_content(body)

        try:
            if self.smtp_use_tls:
                try:
                    import certifi

                    context = ssl.create_default_context(cafile=certifi.where())
                except Exception:
                    context = ssl.create_default_context()
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    if self.smtp_username and self.smtp_password:
                        server.login(self.smtp_username, self.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                    if self.smtp_username and self.smtp_password:
                        server.login(self.smtp_username, self.smtp_password)
                    server.send_message(msg)
        except smtplib.SMTPException as exc:
            raise ProviderError(str(exc), provider=self.name, retryable=True) from exc
        except ssl.SSLError as exc:
            raise ProviderError(str(exc), provider=self.name, retryable=True) from exc
        return f"smtp-{uuid4()}"

    def _send_resend(self, *, to: list[str], subject: str, body: str) -> str:
        if not self.api_key:
            raise ProviderError(
                "Resend API key not configured (EMAIL_API_KEY)",
                provider=self.name,
                retryable=False,
            )
        payload = {
            "from": self.from_address,
            "to": to,
            "subject": subject,
            "text": body,
        }
        req = urlrequest.Request(
            f"{self.resend_base_url}/emails",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw) if raw else {}
                return str(data.get("id") or f"resend-{uuid4()}")
        except urlerror.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code in {408, 429, 500, 502, 503, 504}
            raise ProviderError(
                f"Resend HTTP {exc.code}: {detail}",
                provider=self.name,
                retryable=retryable,
            ) from exc
        except urlerror.URLError as exc:
            raise ProviderTimeoutError(str(exc.reason), provider=self.name) from exc

    def get_message(self, *, organization_id: UUID, message_id: str) -> EmailMessage | None:
        return self._outbox.get_message(
            organization_id=organization_id, message_id=message_id
        )

    def get_thread(self, *, organization_id: UUID, thread_id: str) -> list[EmailMessage]:
        return self._outbox.get_thread(
            organization_id=organization_id, thread_id=thread_id
        )

    def get_delivery_status(self, *, organization_id: UUID, message_id: str) -> str:
        return self._outbox.get_delivery_status(
            organization_id=organization_id, message_id=message_id
        )
