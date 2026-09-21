import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from typing_extensions import TypedDict

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Payment, PaymentStatusHistory
from app.schemas import PaymentCreate
from app.services.event_system import EventType, emit_event
from app.services.validation import (
    validate_account_number,
    validate_amount,
    validate_payment_reason,
    validate_routing_number,
)

logger = logging.getLogger(__name__)


class PaymentResponseDict(TypedDict):
    transaction_id: str
    status: str
    amount: float
    routing_number: str
    account_number: str
    payment_reason: str
    batch_id: Optional[str]
    return_code: Optional[str]
    failure_reason: Optional[str]
    created_at: datetime
    updated_at: datetime
    batched_at: Optional[datetime]
    sent_at: Optional[datetime]
    settled_at: Optional[datetime]


class HistoryResponse(TypedDict):
    previous_status: Optional[str]
    new_status: str
    timestamp: str
    notes: Optional[str]


class EventResponse(TypedDict):
    event_type: str
    timestamp: str
    payload: Optional[str]


class PaymentError(HTTPException):
    pass


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _serialize_timestamp(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    return _ensure_utc(dt).isoformat()


def _to_response(payment: Payment) -> PaymentResponseDict:
    return {
        "transaction_id": payment.id,
        "status": payment.status,
        "amount": payment.amount,
        "routing_number": payment.routing_number,
        "account_number": payment.account_number,
        "payment_reason": payment.payment_reason,
        "batch_id": payment.batch_id,
        "return_code": payment.return_code,
        "failure_reason": payment.failure_reason,
        "created_at": _ensure_utc(payment.created_at),
        "updated_at": _ensure_utc(payment.updated_at),
        "batched_at": _ensure_utc(payment.batched_at) if payment.batched_at else None,
        "sent_at": _ensure_utc(payment.sent_at) if payment.sent_at else None,
        "settled_at": _ensure_utc(payment.settled_at) if payment.settled_at else None,
    }


def create_payment(db: Session, payload: PaymentCreate) -> PaymentResponseDict:
    logger.info("Received payment request with idempotency_key=%s", payload.idempotency_key)

    existing = db.query(Payment).filter(Payment.idempotency_key == payload.idempotency_key).first()
    if existing:
        logger.error("Duplicate idempotency key rejected: %s", payload.idempotency_key)
        raise PaymentError(status_code=status.HTTP_409_CONFLICT, detail="Duplicate idempotency_key")

    is_valid, error = validate_amount(payload.amount)
    if not is_valid:
        logger.error("Amount validation failed: %s", error)
        raise PaymentError(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    is_valid, error = validate_routing_number(payload.routing_number)
    if not is_valid:
        logger.error("Routing number validation failed: %s", error)
        raise PaymentError(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    is_valid, error = validate_account_number(payload.account_number)
    if not is_valid:
        logger.error("Account number validation failed: %s", error)
        raise PaymentError(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    is_valid, error = validate_payment_reason(payload.payment_reason)
    if not is_valid:
        logger.error("Payment reason validation failed: %s", error)
        raise PaymentError(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    payment = Payment(
        id=str(uuid.uuid4()),
        amount=payload.amount,
        routing_number=payload.routing_number,
        account_number=payload.account_number,
        payment_reason=payload.payment_reason,
        idempotency_key=payload.idempotency_key,
        status="Requested",
        extracted_for_batch=False,
    )
    db.add(payment)
    db.flush()

    emit_event(
        db,
        EventType.PAYMENT_CREATED,
        payment.id,
        {
            "amount": payment.amount,
            "routing_number": payment.routing_number,
            "payment_reason": payment.payment_reason,
        },
    )

    db.add(
        PaymentStatusHistory(
            transaction_id=payment.id,
            previous_status=None,
            new_status="Requested",
            timestamp=datetime.now(timezone.utc),
            notes="Payment created and queued for batch processing",
        )
    )

    db.commit()
    db.refresh(payment)
    logger.info("Payment stored successfully transaction_id=%s", payment.id)
    return _to_response(payment)


def get_payment_by_id(db: Session, payment_id: str) -> Optional[PaymentResponseDict]:
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        return None
    return _to_response(payment)


def list_payments(db: Session, status_filter: Optional[str] = None) -> list[PaymentResponseDict]:
    query = db.query(Payment)
    if status_filter:
        query = query.filter(Payment.status == status_filter)
    payments = query.order_by(Payment.created_at.desc()).all()
    return [_to_response(payment) for payment in payments]


def get_payment_history(db: Session, payment_id: str) -> list[HistoryResponse]:
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        return []
    return [
        {
            "previous_status": history.previous_status,
            "new_status": history.new_status,
            "timestamp": _serialize_timestamp(history.timestamp),
            "notes": history.notes,
        }
        for history in payment.status_history
    ]


def get_payment_events(db: Session, payment_id: str) -> list[EventResponse]:
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        return []
    return [
        {
            "event_type": event.event_type,
            "timestamp": _serialize_timestamp(event.timestamp),
            "payload": event.payload,
        }
        for event in payment.events
    ]


def cancel_payment(db: Session, payment_id: str) -> PaymentResponseDict:
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        logger.error("Payment not found: %s", payment_id)
        raise PaymentError(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    if payment.status != "Requested":
        logger.error("Cannot cancel payment %s with status %s", payment_id, payment.status)
        raise PaymentError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot cancel payment after it has been {payment.status.lower()}. "
                "Only payments in 'Requested' status can be cancelled."
            ),
        )

    payment.status = "Cancelled"
    payment.updated_at = datetime.now(timezone.utc)
    db.add(
        PaymentStatusHistory(
            transaction_id=payment.id,
            previous_status="Requested",
            new_status="Cancelled",
            timestamp=datetime.now(timezone.utc),
            notes="Payment cancelled by user",
        )
    )
    emit_event(
        db,
        EventType.PAYMENT_CANCELLED,
        payment.id,
        {"cancelled_at": datetime.now(timezone.utc).isoformat()},
    )

    db.commit()
    db.refresh(payment)
    logger.info("Payment %s cancelled successfully", payment_id)
    return _to_response(payment)
