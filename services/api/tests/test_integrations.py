"""Integration adapter tests — providers, email, quotations, PO approval."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.agents.execution.quotations import (
    compare_quotations,
    extract_quotation_from_text,
    normalize_quotation,
)
from app.database.memory import get_memory_store
from app.domain.enums import ApprovalStatus
from app.integrations.credentials import ProviderCredentialStore, SecretVault
from app.integrations.email import MockEmailProvider
from app.integrations.errors import (
    InvalidRecipientError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    SupplierRejectedError,
)
from app.integrations.factory import build_providers
from app.integrations.protocols import EmailAttachment
from app.integrations.purchasing import MockPurchasingProvider
from app.integrations.quotation_workflow import SupplierQuotationWorkflow
from app.integrations.supplier import MockSupplierProvider
from app.repositories.memory_repos import SupplierContactRepository, SupplierRepository


def _seed_suppliers(org_id: UUID) -> list[UUID]:
    repo = SupplierRepository(org_id)
    contacts = SupplierContactRepository(org_id)
    ids: list[UUID] = []
    for i, name in enumerate(["Acme Supplies", "Globex Parts"], start=1):
        s = repo.create(
            name=name,
            code=f"SUP-{i}",
            approval_status="approved",
            status="active",
        )
        contacts.create(
            supplier_id=s.id,
            full_name=f"Contact {i}",
            email=f"quotes{i}@supplier.example",
            is_primary=True,
        )
        ids.append(s.id)
    return ids


def test_successful_email_send(org_a: UUID) -> None:
    email = MockEmailProvider()
    draft = email.create_draft(
        organization_id=org_a,
        to=["buyer@example.com"],
        subject="Hello",
        body="Body",
        idempotency_key="send-1-draft",
        attachments=[
            EmailAttachment(
                filename="spec.pdf",
                content_type="application/pdf",
                content_b64="c3BlYw==",
            )
        ],
    )
    assert draft.status == "draft"
    assert draft.thread_id
    assert draft.attachments

    sent = email.send_email(
        organization_id=org_a,
        to=["buyer@example.com"],
        subject="Hello",
        body="Body",
        idempotency_key="send-1",
        draft_id=draft.id,
    )
    assert sent.status in {"sent", "delivered"}
    assert sent.provider_message_id
    assert sent.thread_id == draft.thread_id
    assert email.get_delivery_status(organization_id=org_a, message_id=sent.id) == "sent"
    thread = email.get_thread(organization_id=org_a, thread_id=sent.thread_id or "")
    assert any(m.id == sent.id for m in thread)


def test_invalid_recipients(org_a: UUID) -> None:
    email = MockEmailProvider()
    with pytest.raises(InvalidRecipientError) as exc:
        email.validate_recipients(["not-an-email", "also bad"])
    assert "not-an-email" in exc.value.recipients

    with pytest.raises(InvalidRecipientError):
        email.send_email(
            organization_id=org_a,
            to=["bad-address"],
            subject="x",
            body="y",
            idempotency_key="bad-1",
        )


def test_provider_timeout(org_a: UUID) -> None:
    email = MockEmailProvider(force_timeout=True)
    with pytest.raises(ProviderTimeoutError):
        email.send_email(
            organization_id=org_a,
            to=["a@example.com"],
            subject="t",
            body="b",
            idempotency_key="timeout-1",
        )

    supplier = MockSupplierProvider(force_timeout=True)
    _seed_suppliers(org_a)
    draft = supplier.create_quotation_request_draft(
        organization_id=org_a,
        supplier_id=str(next(iter(get_memory_store().suppliers))),
        product_sku="SKU-1",
        quantity=2,
        contact_email="c@example.com",
        idempotency_key="sup-to",
    )
    with pytest.raises(ProviderTimeoutError):
        supplier.send_quotation_request(
            organization_id=org_a,
            draft_id=draft.id,
            idempotency_key="sup-to-send",
            authorized=True,
        )


def test_provider_rate_limit(org_a: UUID) -> None:
    email = MockEmailProvider(force_rate_limit=True)
    with pytest.raises(ProviderRateLimitError) as exc:
        email.send_email(
            organization_id=org_a,
            to=["a@example.com"],
            subject="t",
            body="b",
            idempotency_key="rl-1",
        )
    assert exc.value.retryable is True


def test_duplicate_send_prevention(org_a: UUID) -> None:
    email = MockEmailProvider()
    first = email.send_email(
        organization_id=org_a,
        to=["a@example.com"],
        subject="Once",
        body="Body",
        idempotency_key="dup-key",
    )
    second = email.send_email(
        organization_id=org_a,
        to=["a@example.com"],
        subject="Once again",
        body="Different",
        idempotency_key="dup-key",
    )
    assert first.id == second.id
    assert first.provider_message_id == second.provider_message_id
    # Only one sent/delivered record for the key
    sent = [
        m
        for m in get_memory_store().email_outbox.values()
        if m.get("idempotency_key") == "dup-key" and m.get("status") in {"sent", "delivered"}
    ]
    assert len(sent) == 1


def test_quote_extraction_and_missing_fields() -> None:
    rich = extract_quotation_from_text(
        "Unit price: $99.50 USD qty: 10 tax: 8 shipping: 12 delivery days: 5 warranty: 24 each"
    )
    assert rich["unit_price"] == 99.5
    assert rich["currency"] == "USD"
    assert rich["tax"] == 8.0
    assert rich["shipping"] == 12.0
    assert rich["delivery_days"] == 5
    assert rich["warranty_months"] == 24

    sparse = extract_quotation_from_text("Thanks for your inquiry, we will reply later.")
    assert sparse["unit_price"] == 0.0
    assert sparse["delivery_days"] is None


def test_currency_normalization_tax_shipping() -> None:
    eur = normalize_quotation(
        {
            "id": "q-eur",
            "supplier_id": "s1",
            "currency": "EUR",
            "unit_price": 100.0,
            "quantity": 2,
            "tax": 10.0,
            "shipping": 20.0,
            "unit": "each",
            "delivery_days": 7,
            "warranty_months": 12,
        }
    )
    assert eur.fx_rate_to_usd == 1.08
    assert eur.subtotal_usd == pytest.approx(216.0, rel=1e-3)
    assert eur.tax_usd == pytest.approx(10.8, rel=1e-3)
    assert eur.shipping_usd == pytest.approx(21.6, rel=1e-3)
    assert eur.total_cost_usd == pytest.approx(216.0 + 10.8 + 21.6, rel=1e-3)

    usd = normalize_quotation(
        {
            "id": "q-usd",
            "supplier_id": "s2",
            "currency": "USD",
            "unit_price": 200.0,
            "quantity": 2,
            "tax": 0.0,
            "shipping": 0.0,
            "unit": "each",
        }
    )
    result = compare_quotations([eur, usd])
    assert result.deterministic is True
    assert result.winner_quotation_id in {"q-eur", "q-usd"}


def test_supplier_rejection(org_a: UUID) -> None:
    supplier_ids = _seed_suppliers(org_a)
    supplier = MockSupplierProvider(force_reject=True)
    draft = supplier.create_quotation_request_draft(
        organization_id=org_a,
        supplier_id=str(supplier_ids[0]),
        product_sku="LAPTOP",
        quantity=3,
        contact_email="quotes1@supplier.example",
        idempotency_key="reject-draft",
    )
    with pytest.raises(SupplierRejectedError):
        supplier.send_quotation_request(
            organization_id=org_a,
            draft_id=draft.id,
            idempotency_key="reject-send",
            authorized=True,
        )


def test_purchase_order_approval_flow(org_a: UUID, user_a_id: UUID) -> None:
    _seed_suppliers(org_a)
    purchasing = MockPurchasingProvider()
    po = purchasing.create_purchase_order_draft(
        organization_id=org_a,
        supplier_id=str(next(iter(get_memory_store().suppliers))),
        amount_total=500.0,
        currency_code="USD",
        lines=[{"sku": "X", "quantity": 1, "unit_price": 500}],
        idempotency_key="po-1",
    )
    assert po.status == "draft"

    with pytest.raises(PermissionError):
        purchasing.submit_purchase_order(
            organization_id=org_a,
            purchase_order_id=po.id,
            idempotency_key="po-1-submit",
            approved=False,
        )

    approval_id = str(uuid4())
    pending = purchasing.request_approval(
        organization_id=org_a,
        purchase_order_id=po.id,
        approval_id=approval_id,
    )
    assert pending.status == "pending_approval"

    submitted = purchasing.submit_purchase_order(
        organization_id=org_a,
        purchase_order_id=po.id,
        idempotency_key="po-1-submit",
        approved=True,
    )
    assert submitted.status == "submitted"
    assert submitted.external_ref


def test_quotation_workflow_end_to_end(org_a: UUID, user_a_id: UUID) -> None:
    supplier_ids = _seed_suppliers(org_a)
    wf = SupplierQuotationWorkflow(build_providers(force_mock=True))

    awaiting = wf.run(
        organization_id=org_a,
        product_sku="NB-14",
        quantity=5,
        authorized_to_send=False,
        show_drafts=True,
        idempotency_prefix="wf-await",
    )
    assert awaiting.status == "awaiting_authorization"
    assert awaiting.drafts
    assert any(s["step"] == "show_draft" for s in awaiting.steps)

    texts = {
        str(supplier_ids[0]): (
            "Unit price: $110 USD qty: 5 tax: 20 shipping: 30 delivery 8 warranty 12 each"
        ),
        str(supplier_ids[1]): (
            "Unit price: $105 EUR qty: 5 tax: 15 shipping: 25 delivery 6 warranty 24 each"
        ),
    }
    result = wf.run(
        organization_id=org_a,
        product_sku="NB-14",
        quantity=5,
        authorized_to_send=True,
        response_texts=texts,
        idempotency_prefix="wf-full",
    )
    step_names = [s["step"] for s in result.steps]
    for required in [
        "retrieve_approved_suppliers",
        "retrieve_supplier_contacts",
        "create_quotation_request_draft",
        "send_quotation_request",
        "store_outbound_metadata",
        "ingest_response",
        "extract_quote_fields",
        "normalize_quotes",
        "compare_quotes",
        "generate_recommendation",
        "create_purchase_order_draft",
        "request_approval",
    ]:
        assert required in step_names

    assert result.recommendation is not None
    assert result.purchase_order is not None
    assert result.approval_id is not None
    assert result.status == "awaiting_po_approval"

    done = wf.approve_and_submit_po(
        organization_id=org_a,
        purchase_order_id=result.purchase_order["id"],
        approval_id=result.approval_id,
        decided_by_user_id=user_a_id,
        idempotency_key="wf-po-submit",
    )
    assert done["status"] == "submitted"
    assert get_memory_store().approvals[result.approval_id].status == ApprovalStatus.APPROVED


def test_encrypted_credentials_not_stored_plaintext(org_a: UUID) -> None:
    vault = SecretVault(master_secret="test-master-secret")
    store = ProviderCredentialStore(vault=vault)
    secret = "super-secret-api-key-value"
    cred_id = store.put(
        organization_id=org_a,
        provider="email",
        secret_value=secret,
        label="primary",
    )
    record = get_memory_store().encrypted_credentials[cred_id]
    blob = str(record)
    assert secret not in blob
    assert "api_key" not in record
    assert "sealed" in record
    assert store.get_secret(organization_id=org_a, provider="email") == secret
    assert store.has_credentials(organization_id=org_a, provider="email")


def test_factory_defaults_to_mock() -> None:
    bundle = build_providers(force_mock=True)
    assert bundle.email.name.startswith("mock_")
    assert bundle.supplier.name.startswith("mock_")
    assert bundle.purchasing.name.startswith("mock_")
    assert bundle.billing.name.startswith("mock_")
    assert isinstance(bundle.calendar.name, str)
    assert isinstance(bundle.identity.name, str)


def test_email_failure_tracking(org_a: UUID) -> None:
    email = MockEmailProvider()
    sent = email.send_email(
        organization_id=org_a,
        to=["ok@example.com"],
        subject="x",
        body="y",
        idempotency_key="fail-track",
    )
    failed = email.mark_failed(
        organization_id=org_a, message_id=sent.id, reason="bounce"
    )
    assert failed.status == "failed"
    assert failed.failure_reason == "bounce"
