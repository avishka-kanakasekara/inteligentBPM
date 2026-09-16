"""Workspace artifacts produced by Agent 4 tools (documents, calendar, tasks, notifications, emails)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.auth.deps import OrganizationContext, require_permission
from app.contracts.common import utcnow
from app.database.memory import get_memory_store
from app.permissions import codes as perm

router = APIRouter(tags=["workspace"])

_DOC_TYPE_LABELS = {
    "rfq": "Request for quotation pack",
    "memo": "Internal memo",
    "po": "Purchase order summary",
    "po_summary": "Purchase order summary",
    "summary": "Process summary",
    "report": "Process report",
}


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or utcnow().isoformat())


def _preview(text: str, limit: int = 280) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _word_count(text: str) -> int:
    return len([w for w in str(text or "").split() if w])


def _process_name(organization_id: UUID, process_id: Any) -> str | None:
    if not process_id:
        return None
    store = get_memory_store()
    try:
        pid = UUID(str(process_id))
    except Exception:
        return None
    proc = store.processes.get(pid)
    if proc is None or proc.organization_id != organization_id:
        return None
    return proc.name


def _org_items(collection: dict, organization_id: UUID) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in collection.values():
        if not isinstance(raw, dict):
            continue
        if str(raw.get("organization_id")) != str(organization_id):
            continue
        items.append(raw)
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return items


def serialize_notification(raw: dict[str, Any], *, organization_id: UUID) -> dict[str, Any]:
    delivery = str(raw.get("status") or "sent")
    inbox_status = raw.get("inbox_status")
    if inbox_status not in {"unread", "read"}:
        inbox_status = "unread" if delivery in {"sent", "unread", ""} else "read"
    title = str(raw.get("title") or "").strip() or "Process notification"
    body = str(raw.get("body") or raw.get("message") or "")
    to = list(raw.get("to") or [])
    display_name = raw.get("display_name")
    process_id = raw.get("process_id")
    process_name = _process_name(organization_id, process_id)
    recipients = ", ".join(to) if to else (display_name or "internal recipient")
    summary = (
        f"Notified {recipients}"
        + (f" about “{title}”" if title else "")
        + (f" for process “{process_name}”" if process_name else "")
        + "."
    )
    return {
        "id": str(raw.get("id")),
        "title": title,
        "body": body,
        "body_preview": _preview(body, 320),
        "summary": summary,
        "status": inbox_status,
        "delivery_status": delivery,
        "to": to,
        "user_id": raw.get("user_id"),
        "display_name": display_name,
        "email_status": raw.get("email_status"),
        "provider_message_id": raw.get("provider_message_id"),
        "process_id": process_id,
        "process_name": process_name,
        "mock": bool(raw.get("mock", False)),
        "provider": raw.get("provider"),
        "created_at": _iso(raw.get("created_at")),
    }


def serialize_calendar_event(raw: dict[str, Any], *, organization_id: UUID) -> dict[str, Any]:
    process_id = raw.get("process_id")
    process_name = _process_name(organization_id, process_id)
    attendees = list(raw.get("attendees") or [])
    invites = list(raw.get("invites_sent") or [])
    title = str(raw.get("title") or "Meeting")
    description = str(raw.get("description") or "")
    summary = (
        f"Scheduled “{title}” with {len(attendees)} attendee(s)"
        + (f"; {len(invites)} invite email(s) sent" if invites else "")
        + (f" for process “{process_name}”" if process_name else "")
        + "."
    )
    return {
        "id": str(raw.get("id")),
        "title": title,
        "description": description,
        "description_preview": _preview(description, 240),
        "summary": summary,
        "start_at": str(raw.get("start_at") or ""),
        "end_at": str(raw.get("end_at") or ""),
        "attendees": attendees,
        "status": str(raw.get("status") or "confirmed"),
        "invites_sent": invites,
        "process_id": process_id,
        "process_name": process_name,
        "mock": bool(raw.get("mock", False)),
        "provider": raw.get("provider"),
        "created_at": _iso(raw.get("created_at")),
    }


def serialize_task(raw: dict[str, Any], *, organization_id: UUID) -> dict[str, Any]:
    process_id = raw.get("process_id")
    process_name = _process_name(organization_id, process_id)
    title = str(raw.get("title") or "Task")
    description = str(raw.get("description") or "")
    assignee = raw.get("assignee_name") or (list(raw.get("to") or [])[:1] or [None])[0] or raw.get("assignee_id")
    summary = (
        f"Assigned “{title}” to {assignee or 'unassigned'}"
        + (f" for process “{process_name}”" if process_name else "")
        + "."
    )
    return {
        "id": str(raw.get("id")),
        "title": title,
        "description": description,
        "description_preview": _preview(description, 240),
        "summary": summary,
        "assignee_id": raw.get("assignee_id"),
        "assignee_name": raw.get("assignee_name"),
        "to": list(raw.get("to") or []),
        "due_at": raw.get("due_at"),
        "status": str(raw.get("status") or "open"),
        "email_status": raw.get("email_status"),
        "process_id": process_id,
        "process_name": process_name,
        "mock": bool(raw.get("mock", False)),
        "provider": raw.get("provider"),
        "created_at": _iso(raw.get("created_at")),
    }


def serialize_generated_document(raw: dict[str, Any], *, organization_id: UUID) -> dict[str, Any]:
    content = str(raw.get("content") or "")
    doc_type = str(raw.get("doc_type") or "memo")
    title = str(raw.get("title") or "Document")
    process_id = raw.get("process_id")
    process_name = _process_name(organization_id, process_id)
    type_label = _DOC_TYPE_LABELS.get(doc_type.lower(), doc_type.replace("_", " ").title())
    words = _word_count(content)
    summary = (
        f"{type_label}: “{title}” ({words} words)"
        + (f" created for process “{process_name}”" if process_name else "")
        + "."
    )
    return {
        "id": str(raw.get("id")),
        "title": title,
        "doc_type": doc_type,
        "doc_type_label": type_label,
        "content": content,
        "content_preview": _preview(content, 360),
        "summary": summary,
        "word_count": words,
        "byte_size": int(raw.get("byte_size") or len(content.encode("utf-8"))),
        "status": str(raw.get("status") or "generated"),
        "process_id": process_id,
        "process_name": process_name,
        "mock": bool(raw.get("mock", False)),
        "provider": raw.get("provider"),
        "created_at": _iso(raw.get("created_at")),
    }


def serialize_email(raw: dict[str, Any], *, organization_id: UUID) -> dict[str, Any]:
    to = list(raw.get("to") or [])
    subject = str(raw.get("subject") or "(no subject)")
    body = str(raw.get("body") or "")
    status = str(raw.get("status") or "sent")
    process_id = raw.get("process_id")
    process_name = _process_name(organization_id, process_id)
    recipients = ", ".join(to) if to else "unknown recipient"
    summary = (
        f"{'Sent' if status == 'sent' else status.title()} “{subject}” to {recipients}"
        + (f" for process “{process_name}”" if process_name else "")
        + "."
    )
    return {
        "id": str(raw.get("id")),
        "to": to,
        "subject": subject,
        "body": body,
        "body_preview": _preview(body, 360),
        "summary": summary,
        "status": status,
        "provider": raw.get("provider"),
        "provider_message_id": raw.get("provider_message_id"),
        "thread_id": raw.get("thread_id"),
        "mock": bool(raw.get("mock", False)),
        "process_id": process_id,
        "process_name": process_name,
        "created_at": _iso(raw.get("created_at") or raw.get("updated_at")),
    }


@router.get("/notifications")
async def list_notifications(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
    process_id: UUID | None = Query(default=None),
) -> list[dict[str, Any]]:
    store = get_memory_store()
    items = _org_items(store.notifications, org.organization_id)
    if process_id is not None:
        items = [i for i in items if str(i.get("process_id") or "") == str(process_id)]
    return [serialize_notification(i, organization_id=org.organization_id) for i in items]


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> dict[str, Any]:
    store = get_memory_store()
    raw = store.notifications.get(notification_id)
    if raw is None or str(raw.get("organization_id")) != str(org.organization_id):
        from app.security.errors import NotFoundError

        raise NotFoundError("Notification not found")
    raw["inbox_status"] = "read"
    store.notifications[notification_id] = raw
    return serialize_notification(raw, organization_id=org.organization_id)


@router.get("/calendar-events")
async def list_calendar_events(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
    process_id: UUID | None = Query(default=None),
) -> list[dict[str, Any]]:
    store = get_memory_store()
    items = _org_items(store.calendar_events, org.organization_id)
    if process_id is not None:
        items = [i for i in items if str(i.get("process_id") or "") == str(process_id)]
    return [serialize_calendar_event(i, organization_id=org.organization_id) for i in items]


@router.get("/tasks")
async def list_tasks(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
    process_id: UUID | None = Query(default=None),
) -> list[dict[str, Any]]:
    store = get_memory_store()
    items = _org_items(getattr(store, "tasks", {}) or {}, org.organization_id)
    if process_id is not None:
        items = [i for i in items if str(i.get("process_id") or "") == str(process_id)]
    return [serialize_task(i, organization_id=org.organization_id) for i in items]


@router.get("/generated-documents")
async def list_generated_documents(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
    process_id: UUID | None = Query(default=None),
) -> list[dict[str, Any]]:
    store = get_memory_store()
    items = _org_items(getattr(store, "generated_documents", {}) or {}, org.organization_id)
    if process_id is not None:
        items = [i for i in items if str(i.get("process_id") or "") == str(process_id)]
    return [serialize_generated_document(i, organization_id=org.organization_id) for i in items]


@router.get("/generated-documents/{document_id}")
async def get_generated_document(
    document_id: UUID,
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
) -> dict[str, Any]:
    store = get_memory_store()
    raw = (getattr(store, "generated_documents", {}) or {}).get(document_id)
    if raw is None or str(raw.get("organization_id")) != str(org.organization_id):
        from app.security.errors import NotFoundError

        raise NotFoundError("Generated document not found")
    return serialize_generated_document(raw, organization_id=org.organization_id)


@router.get("/emails")
async def list_emails(
    org: Annotated[OrganizationContext, Depends(require_permission(perm.PROCESSES_READ))],
    process_id: UUID | None = Query(default=None),
) -> list[dict[str, Any]]:
    store = get_memory_store()
    items = _org_items(store.email_outbox, org.organization_id)
    if process_id is not None:
        items = [i for i in items if str(i.get("process_id") or "") == str(process_id)]
    return [serialize_email(i, organization_id=org.organization_id) for i in items]
