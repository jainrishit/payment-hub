"""
Backend QA tests for Payment Hub.

Covers:
  - Payment creation and validation
  - Idempotency enforcement
  - Full lifecycle: Requested → Batched → Sent → Settled / Returned / Failed
  - Invalid lifecycle transitions (must be rejected)
  - Bank simulation with no Sent payments (empty result)
  - Batch run with no Requested payments (empty result)
  - Payment cancellation rules
  - Load-samples endpoint
"""

import pytest
from collections.abc import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.main import app, get_db
from app.models import Base, Payment
from app.services.batch_service import process_end_of_day_batch
from app.services.bank_simulator import simulate_bank_processing
from app.services.event_system import PaymentLifecycleEngine
from app.services.payment_service import cancel_payment


# ── Per-test isolated database using temp file ────────────────────────────────

@pytest.fixture()
def db_engine(tmp_path):
    db_file = tmp_path / "test_payments.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(db_engine) -> Generator[Session, None, None]:
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture()
def client(db_engine) -> Generator[TestClient, None, None]:
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def _get_test_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_test_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


AUTH = {"Authorization": "Bearer mock-token"}

VALID_PAYMENT = {
    "amount": 2500.00,
    "routing_number": "021000021",
    "account_number": "123456789",
    "payment_reason": "Auto Claim Settlement",
    "idempotency_key": "test-key-001",
}


# ── Helper ─────────────────────────────────────────────────────────────────────

def _create_payment_api(client, overrides=None):
    payload = {**VALID_PAYMENT, **(overrides or {})}
    return client.post("/payments", json=payload, headers=AUTH)


# ── Payment creation ───────────────────────────────────────────────────────────

def test_create_payment_success(client):
    res = _create_payment_api(client)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "Requested"
    assert data["amount"] == 2500.00
    assert data["payment_reason"] == "Auto Claim Settlement"
    assert "transaction_id" in data


def test_create_payment_returns_transaction_id(client):
    res = _create_payment_api(client)
    assert res.status_code == 201
    assert len(res.json()["transaction_id"]) > 0


def test_create_payment_invalid_routing_number(client):
    # 123456789 fails ABA checksum: 3*(1+4+7)+7*(2+5+8)+(3+6+9)=36+105+18=159, not divisible by 10
    res = _create_payment_api(client, {"routing_number": "123456789"})
    assert res.status_code == 400
    assert "routing" in res.json()["detail"].lower()


def test_create_payment_routing_too_short(client):
    res = _create_payment_api(client, {"routing_number": "12345678"})
    assert res.status_code == 422


def test_create_payment_routing_non_numeric(client):
    res = _create_payment_api(client, {"routing_number": "12345678X"})
    assert res.status_code == 422


def test_create_payment_zero_amount(client):
    res = _create_payment_api(client, {"amount": 0})
    assert res.status_code == 422


def test_create_payment_negative_amount(client):
    res = _create_payment_api(client, {"amount": -100})
    assert res.status_code == 422


def test_create_payment_empty_reason(client):
    res = _create_payment_api(client, {"payment_reason": ""})
    assert res.status_code == 422


def test_create_payment_any_reason_accepted(client):
    """Backend no longer restricts to an allowlist of reasons."""
    for reason in ["Auto Claim Settlement", "Property Damage Claim", "Premium Refund",
                   "Disability Benefit", "Catastrophe Claim Settlement"]:
        res = _create_payment_api(client, {
            "payment_reason": reason,
            "idempotency_key": f"key-{reason[:10]}",
        })
        assert res.status_code == 201, f"Reason '{reason}' was rejected: {res.json()}"


# ── Idempotency ────────────────────────────────────────────────────────────────

def test_duplicate_idempotency_key_rejected(client):
    _create_payment_api(client)
    res = _create_payment_api(client)
    assert res.status_code == 409
    assert "idempotency" in res.json()["detail"].lower() or "duplicate" in res.json()["detail"].lower()


def test_different_idempotency_keys_allowed(client):
    res1 = _create_payment_api(client, {"idempotency_key": "key-aaa"})
    res2 = _create_payment_api(client, {"idempotency_key": "key-bbb"})
    assert res1.status_code == 201
    assert res2.status_code == 201


# ── Lifecycle engine ───────────────────────────────────────────────────────────

def test_lifecycle_valid_transitions(db):
    payment = Payment(
        id="p1", amount=100.0, routing_number="021000021",
        account_number="123456789", payment_reason="Test",
        idempotency_key="lc-001", status="Requested", extracted_for_batch=False,
    )
    db.add(payment)
    db.commit()

    assert PaymentLifecycleEngine.transition_payment_status(db, payment, "Batched") is True
    assert payment.status == "Batched"

    assert PaymentLifecycleEngine.transition_payment_status(db, payment, "Sent") is True
    assert payment.status == "Sent"

    assert PaymentLifecycleEngine.transition_payment_status(db, payment, "Settled") is True
    assert payment.status == "Settled"


def test_lifecycle_returned_path(db):
    payment = Payment(
        id="p2", amount=100.0, routing_number="021000021",
        account_number="123456789", payment_reason="Test",
        idempotency_key="lc-002", status="Sent", extracted_for_batch=True,
    )
    db.add(payment)
    db.commit()
    assert PaymentLifecycleEngine.transition_payment_status(db, payment, "Returned") is True
    assert payment.status == "Returned"


def test_lifecycle_cannot_skip_batched(db):
    """Requested → Sent must be rejected; must go through Batched first."""
    payment = Payment(
        id="p3", amount=100.0, routing_number="021000021",
        account_number="123456789", payment_reason="Test",
        idempotency_key="lc-003", status="Requested", extracted_for_batch=False,
    )
    db.add(payment)
    db.commit()
    assert PaymentLifecycleEngine.transition_payment_status(db, payment, "Sent") is False
    assert payment.status == "Requested"


def test_lifecycle_settled_is_terminal(db):
    """Settled payments cannot be transitioned to any other state."""
    payment = Payment(
        id="p4", amount=100.0, routing_number="021000021",
        account_number="123456789", payment_reason="Test",
        idempotency_key="lc-004", status="Settled", extracted_for_batch=True,
    )
    db.add(payment)
    db.commit()
    for target in ["Returned", "Failed", "Batched", "Requested"]:
        ok = PaymentLifecycleEngine.transition_payment_status(db, payment, target)
        assert ok is False, f"Expected rejection for Settled → {target}"
    assert payment.status == "Settled"


def test_lifecycle_cancelled_is_terminal(db):
    payment = Payment(
        id="p5", amount=100.0, routing_number="021000021",
        account_number="123456789", payment_reason="Test",
        idempotency_key="lc-005", status="Cancelled", extracted_for_batch=False,
    )
    db.add(payment)
    db.commit()
    assert PaymentLifecycleEngine.transition_payment_status(db, payment, "Requested") is False


# ── Batch service ──────────────────────────────────────────────────────────────

def test_batch_with_no_requested_payments_returns_empty(db):
    result = process_end_of_day_batch(db)
    assert result["batch_id"] is None
    assert result["total_transactions"] == 0
    assert "no" in result["message"].lower() or "0" in result["message"].lower() or result["total_transactions"] == 0


def test_batch_processes_requested_payments(db):
    payment = Payment(
        id="b1", amount=2500.0, routing_number="021000021",
        account_number="123456789", payment_reason="Auto Claim Settlement",
        idempotency_key="batch-001", status="Requested", extracted_for_batch=False,
    )
    db.add(payment)
    db.commit()

    result = process_end_of_day_batch(db)
    assert result["batch_id"] is not None
    assert result["total_transactions"] == 1
    assert result["total_amount"] == 2500.0

    db.refresh(payment)
    assert payment.status == "Sent"
    assert payment.extracted_for_batch is True


def test_batch_skips_already_extracted_payments(db):
    p1 = Payment(
        id="b2", amount=100.0, routing_number="021000021",
        account_number="123456789", payment_reason="Test",
        idempotency_key="batch-002", status="Requested", extracted_for_batch=True,
    )
    db.add(p1)
    db.commit()

    result = process_end_of_day_batch(db)
    assert result["batch_id"] is None  # already extracted, should not be picked up


# ── Bank simulation ────────────────────────────────────────────────────────────

def test_simulate_bank_with_no_sent_payments_returns_zero(db, tmp_path, monkeypatch):
    import app.services.bank_simulator as bs
    monkeypatch.setattr(bs, "OUTPUT_DIR", tmp_path)
    result = simulate_bank_processing(db)
    assert result["total"] == 0
    assert "no sent" in result["message"].lower() or result["total"] == 0


def test_simulate_bank_processes_sent_payments(db, tmp_path, monkeypatch):
    import app.services.bank_simulator as bs
    import app.services.nacha_generator as ng
    monkeypatch.setattr(bs, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ng, "OUTPUT_DIR", tmp_path)

    # Need a NACHA file (or not — after fix, it's optional)
    payment = Payment(
        id="sim1", amount=2500.0, routing_number="021000021",
        account_number="123456789", payment_reason="Auto Claim Settlement",
        idempotency_key="sim-001", status="Sent", extracted_for_batch=True,
    )
    db.add(payment)
    db.commit()

    result = simulate_bank_processing(db)
    assert result["total"] == 1
    assert result["settled"] + result["returned"] + result["failed"] == 1

    db.refresh(payment)
    assert payment.status in ("Settled", "Returned", "Failed")


# ── Cancellation ───────────────────────────────────────────────────────────────

def test_cancel_requested_payment_succeeds(client):
    create_res = _create_payment_api(client)
    assert create_res.status_code == 201
    payment_id = create_res.json()["transaction_id"]

    cancel_res = client.post(f"/payments/{payment_id}/cancel", headers=AUTH)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "Cancelled"


def test_cancel_nonexistent_payment_returns_404(client):
    res = client.post("/payments/nonexistent-id/cancel", headers=AUTH)
    assert res.status_code == 404


def test_cancel_already_batched_payment_fails(db):
    payment = Payment(
        id="cancel1", amount=100.0, routing_number="021000021",
        account_number="123456789", payment_reason="Test",
        idempotency_key="cancel-001", status="Batched", extracted_for_batch=True,
    )
    db.add(payment)
    db.commit()

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        cancel_payment(db, "cancel1")
    assert exc_info.value.status_code == 400


# ── Load samples endpoint ──────────────────────────────────────────────────────

def test_load_samples_creates_payments(client):
    res = client.post("/load-samples", headers=AUTH)
    assert res.status_code == 200
    data = res.json()
    assert data["data"]["created"] == 6


def test_load_samples_idempotent(client):
    """Calling load-samples twice should not fail and report skips."""
    client.post("/load-samples", headers=AUTH)
    res = client.post("/load-samples", headers=AUTH)
    assert res.status_code == 200
    data = res.json()
    assert data["data"]["created"] == 0
    assert data["data"]["skipped"] == 6


# ── Auth ───────────────────────────────────────────────────────────────────────

def test_missing_auth_header_returns_401(client):
    res = client.post("/payments", json=VALID_PAYMENT)
    assert res.status_code == 401


def test_wrong_auth_token_returns_401(client):
    res = client.post("/payments", json=VALID_PAYMENT,
                      headers={"Authorization": "Bearer wrong-token"})
    assert res.status_code == 401
