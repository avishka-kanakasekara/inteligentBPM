"""Live Agent 4 side-effect tools — persist org records and send real emails via Brevo/SMTP.

These providers keep directory/PO/quote state in the app store and use the configured
EmailProvider for outbound communication (same path as email.send).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from app.contracts.common import utcnow
from app.database.memory import get_memory_store, new_id
from app.integrations.email import MockEmailProvider
from app.integrations.protocols import EmailProvider
from app.integrations.purchasing import MockPurchasingProvider
from app.integrations.supplier import MockSupplierProvider
from app.repositories.memory_repos import (
    EmployeeRepository,
    SupplierContactRepository,
    SupplierRepository,
)


def _now_iso() -> str:
    return utcnow().isoformat()


class LiveSupplierProvider(MockSupplierProvider):
    """Quotation requests that actually email the supplier contact."""

    name = "live_supplier"

    def __init__(self, email: EmailProvider | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.email = email or MockEmailProvider()

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
        email_addr = contact_email or (contacts[0]["email"] if contacts else None)
        supplier = SupplierRepository(organization_id).get(UUID(supplier_id))
        draft = self.create_quotation_request_draft(
            organization_id=organization_id,
            supplier_id=supplier_id,
            product_sku=product_sku,
            quantity=float(quantity),
            contact_email=email_addr,
            idempotency_key=idempotency_key,
        )
        store = get_memory_store()
        record = store.quote_requests[UUID(draft.id)]
        record["subject"] = subject or f"RFQ: {product_sku} × {quantity} — {supplier.name}"
        record["body"] = body or (
            f"Hello,\n\n"
            f"Please provide a formal quotation for:\n"
            f"- SKU / item: {product_sku}\n"
            f"- Quantity: {quantity}\n"
            f"- Supplier: {supplier.name}\n\n"
            f"Include unit price, currency, tax, shipping, delivery lead time, and warranty.\n\n"
            f"Regards,\nAcme Procurement (Agent 4)"
        )
        record["mock"] = False
        record["provider"] = self.name

        outbound_message_id = None
        email_status = None
        if email_addr:
            msg = self.email.send_email(
                organization_id=organization_id,
                to=[email_addr],
                subject=record["subject"],
                body=record["body"],
                idempotency_key=f"{idempotency_key}:email",
            )
            outbound_message_id = msg.provider_message_id or msg.id
            email_status = msg.status
            record["outbound_message_id"] = outbound_message_id
            record["email_status"] = email_status
            record["status"] = "sent"
            record["sent_at"] = _now_iso()
        else:
            sent = self.send_quotation_request(
                organization_id=organization_id,
                draft_id=draft.id,
                idempotency_key=f"{idempotency_key}:send",
                authorized=True,
            )
            outbound_message_id = sent.outbound_message_id
            record["status"] = sent.status

        return {
            "id": draft.id,
            "organization_id": str(organization_id),
            "supplier_id": supplier_id,
            "supplier_name": supplier.name,
            "product_sku": product_sku,
            "quantity": quantity,
            "status": record.get("status"),
            "to": [email_addr] if email_addr else [],
            "subject": record.get("subject"),
            "body": record.get("body"),
            "idempotency_key": idempotency_key,
            "outbound_message_id": outbound_message_id,
            "email_status": email_status,
            "mock": False,
            "provider": self.name,
        }

    def collect_quote(
        self,
        *,
        organization_id: UUID,
        request_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        result = super().collect_quote(
            organization_id=organization_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        result["mock"] = False
        result["provider"] = self.name
        store = get_memory_store()
        qid = UUID(result["id"])
        if qid in store.quotations:
            store.quotations[qid]["mock"] = False
            store.quotations[qid]["provider"] = self.name
        return result


class LivePurchasingProvider(MockPurchasingProvider):
    """Purchase orders persisted locally with optional supplier confirmation email."""

    name = "live_purchasing"

    def __init__(self, email: EmailProvider | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.email = email or MockEmailProvider()

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
        result = super().create_draft(
            organization_id=organization_id,
            supplier_id=supplier_id,
            amount_total=amount_total,
            currency_code=currency_code,
            lines=lines,
            idempotency_key=idempotency_key,
        )
        store = get_memory_store()
        po = store.purchase_orders.get(UUID(result["id"]))
        if po:
            po["mock"] = False
            po["provider"] = self.name
            po["po_number"] = f"PO-{str(result['id'])[:8].upper()}"
            result["po_number"] = po["po_number"]
        result["mock"] = False
        result["provider"] = self.name
        return result

    def submit(
        self,
        *,
        organization_id: UUID,
        purchase_order_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        result = super().submit(
            organization_id=organization_id,
            purchase_order_id=purchase_order_id,
            idempotency_key=idempotency_key,
        )
        store = get_memory_store()
        po = store.purchase_orders.get(UUID(purchase_order_id))
        if po:
            po["mock"] = False
            po["provider"] = self.name
            po["external_ref"] = po.get("po_number") or f"PO-{purchase_order_id[:8].upper()}"
            po["submitted_at"] = _now_iso()
            # Email supplier contact a PO confirmation when possible
            try:
                contacts = SupplierContactRepository(organization_id).list_all(
                    supplier_id=UUID(str(po["supplier_id"]))
                )
                to_email = next((c.email for c in contacts if c.email), None)
                if to_email:
                    subject = f"Purchase Order {po['external_ref']} submitted"
                    body = (
                        f"Hello,\n\n"
                        f"Purchase order {po['external_ref']} has been submitted.\n"
                        f"Amount: {po.get('currency_code', 'USD')} {po.get('amount_total')}\n"
                        f"Lines: {len(po.get('lines') or [])}\n\n"
                        f"Regards,\nAcme Procurement (Agent 4)"
                    )
                    msg = self.email.send_email(
                        organization_id=organization_id,
                        to=[to_email],
                        subject=subject,
                        body=body,
                        idempotency_key=f"{idempotency_key}:po-email",
                    )
                    po["confirmation_email_id"] = msg.id
                    po["confirmation_email_to"] = to_email
                    result["confirmation_email_to"] = to_email
                    result["confirmation_email_status"] = msg.status
            except Exception:
                pass
            result["external_ref"] = po["external_ref"]
            result["po_number"] = po.get("po_number")
        result["mock"] = False
        result["provider"] = self.name
        return result


class LiveNotificationAdapter:
    """In-app notification plus optional email to employee/contact."""

    def __init__(self, email: EmailProvider | None = None) -> None:
        self.email = email or MockEmailProvider()

    def send(
        self,
        *,
        organization_id: UUID,
        user_id: str | None,
        title: str,
        body: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        store = get_memory_store()
        for existing in store.notifications.values():
            if (
                existing.get("organization_id") == str(organization_id)
                and existing.get("idempotency_key") == idempotency_key
            ):
                return existing

        to_email = None
        display_name = None
        if user_id:
            if "@" in user_id:
                to_email = user_id
            else:
                try:
                    emp = EmployeeRepository(organization_id).get(UUID(user_id))
                    to_email = emp.email
                    display_name = emp.full_name
                except Exception:
                    try:
                        for c in SupplierContactRepository(organization_id).list_all():
                            if str(c.id) == user_id and c.email:
                                to_email = c.email
                                display_name = c.full_name
                                break
                    except Exception:
                        pass

        email_status = None
        provider_message_id = None
        if to_email:
            msg = self.email.send_email(
                organization_id=organization_id,
                to=[to_email],
                subject=title,
                body=body,
                idempotency_key=f"{idempotency_key}:email",
            )
            email_status = msg.status
            provider_message_id = msg.provider_message_id or msg.id

        nid = new_id()
        record = {
            "id": str(nid),
            "organization_id": str(organization_id),
            "user_id": user_id,
            "display_name": display_name,
            "to": [to_email] if to_email else [],
            "title": title,
            "body": body,
            "status": "sent",
            "email_status": email_status,
            "provider_message_id": provider_message_id,
            "idempotency_key": idempotency_key,
            "mock": False,
            "provider": "live_notification",
            "created_at": _now_iso(),
        }
        store.notifications[nid] = record
        return record


class LiveCalendarAdapter:
    def __init__(self, email: EmailProvider | None = None) -> None:
        self.email = email or MockEmailProvider()

    def create_event(
        self,
        *,
        organization_id: UUID,
        title: str,
        start_at: str,
        end_at: str | None = None,
        attendees: list[str] | None = None,
        description: str | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        store = get_memory_store()
        for existing in store.calendar_events.values():
            if (
                existing.get("organization_id") == str(organization_id)
                and existing.get("idempotency_key") == idempotency_key
            ):
                return existing

        attendee_emails: list[str] = []
        for raw in attendees or []:
            addr = (raw or "").strip()
            if not addr:
                continue
            if "@" in addr:
                attendee_emails.append(addr.lower())
                continue
            try:
                emp = EmployeeRepository(organization_id).get(UUID(addr))
                if emp.email:
                    attendee_emails.append(emp.email.lower())
            except Exception:
                pass

        if not end_at:
            try:
                start = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
            except Exception:
                start = datetime.now(timezone.utc)
            end_at = (start + timedelta(hours=1)).isoformat()

        event_id = new_id()
        record = {
            "id": str(event_id),
            "organization_id": str(organization_id),
            "title": title,
            "description": description or "",
            "start_at": start_at,
            "end_at": end_at,
            "attendees": attendee_emails,
            "status": "confirmed",
            "provider": "live_calendar",
            "mock": False,
            "idempotency_key": idempotency_key,
            "created_at": _now_iso(),
            "invites_sent": [],
        }
        for addr in attendee_emails:
            try:
                msg = self.email.send_email(
                    organization_id=organization_id,
                    to=[addr],
                    subject=f"Meeting: {title}",
                    body=(
                        f"You are invited to: {title}\n\n"
                        f"Start: {start_at}\n"
                        f"End: {end_at}\n\n"
                        f"{description or ''}\n\n"
                        f"— Acme BPM Agent 4"
                    ),
                    idempotency_key=f"{idempotency_key}:invite:{addr}",
                )
                record["invites_sent"].append(
                    {"to": addr, "status": msg.status, "message_id": msg.id}
                )
            except Exception as exc:  # noqa: BLE001
                record["invites_sent"].append({"to": addr, "status": "failed", "error": str(exc)})

        store.calendar_events[event_id] = record
        return record


class LiveTaskAdapter:
    def __init__(self, email: EmailProvider | None = None) -> None:
        self.email = email or MockEmailProvider()

    def assign(
        self,
        *,
        organization_id: UUID,
        title: str,
        assignee_id: str,
        description: str | None = None,
        due_at: str | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        store = get_memory_store()
        tasks = getattr(store, "tasks", None)
        if tasks is None:
            store.tasks = {}
            tasks = store.tasks

        for existing in tasks.values():
            if (
                existing.get("organization_id") == str(organization_id)
                and existing.get("idempotency_key") == idempotency_key
            ):
                return existing

        to_email = None
        assignee_name = None
        if "@" in assignee_id:
            to_email = assignee_id
            assignee_name = assignee_id
        else:
            try:
                emp = EmployeeRepository(organization_id).get(UUID(assignee_id))
                to_email = emp.email
                assignee_name = emp.full_name
            except Exception:
                assignee_name = assignee_id

        tid = new_id()
        record: dict[str, Any] = {
            "id": str(tid),
            "organization_id": str(organization_id),
            "title": title,
            "description": description or "",
            "assignee_id": assignee_id,
            "assignee_name": assignee_name,
            "to": [to_email] if to_email else [],
            "due_at": due_at,
            "status": "open",
            "idempotency_key": idempotency_key,
            "mock": False,
            "provider": "live_task",
            "created_at": _now_iso(),
        }
        if to_email:
            msg = self.email.send_email(
                organization_id=organization_id,
                to=[to_email],
                subject=f"Task assigned: {title}",
                body=(
                    f"Hello {assignee_name or ''},\n\n"
                    f"You have been assigned a task:\n"
                    f"{title}\n\n"
                    f"{description or ''}\n"
                    f"{'Due: ' + due_at if due_at else ''}\n\n"
                    f"— Acme BPM Agent 4"
                ),
                idempotency_key=f"{idempotency_key}:email",
            )
            record["email_status"] = msg.status
            record["provider_message_id"] = msg.provider_message_id or msg.id
        tasks[tid] = record
        return record


class LiveDocumentAdapter:
    def generate(
        self,
        *,
        organization_id: UUID,
        title: str,
        doc_type: str,
        content: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        store = get_memory_store()
        docs = getattr(store, "generated_documents", None)
        if docs is None:
            store.generated_documents = {}
            docs = store.generated_documents

        for existing in docs.values():
            if (
                existing.get("organization_id") == str(organization_id)
                and existing.get("idempotency_key") == idempotency_key
            ):
                return existing

        did = new_id()
        record = {
            "id": str(did),
            "organization_id": str(organization_id),
            "title": title,
            "doc_type": doc_type,
            "content": content,
            "status": "generated",
            "byte_size": len(content.encode("utf-8")),
            "idempotency_key": idempotency_key,
            "mock": False,
            "provider": "live_document",
            "created_at": _now_iso(),
        }
        docs[did] = record
        return record
