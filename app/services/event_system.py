import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Union

from sqlalchemy.orm import Session

from app.models import Payment, PaymentEvent, PaymentStatusHistory

logger = logging.getLogger(__name__)

JsonPrimitive = Optional[Union[str, int, float, bool]]
JsonValue = Union[JsonPrimitive, list["JsonValue"], dict[str, "JsonValue"]]


class EventType(str, Enum):
    PAYMENT_CREATED = "PAYMENT_CREATED"
    PAYMENT_VALIDATED = "PAYMENT_VALIDATED"
    PAYMENT_BATCHED = "PAYMENT_BATCHED"
    PAYMENT_SENT = "PAYMENT_SENT"
    PAYMENT_SETTLED = "PAYMENT_SETTLED"
    PAYMENT_RETURNED = "PAYMENT_RETURNED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAYMENT_CANCELLED = "PAYMENT_CANCELLED"
    BATCH_CREATED = "BATCH_CREATED"
    BATCH_PROCESSED = "BATCH_PROCESSED"


class PaymentLifecycleEngine:
    """Manages payment lifecycle state transitions with strict rules."""

    VALID_TRANSITIONS: dict[Optional[str], list[str]] = {
        None: ["Requested"],
        "Requested": ["Batched", "Failed", "Cancelled"],
        "Batched": ["Sent", "Failed"],
        "Sent": ["Settled", "Returned", "Failed"],
        "Settled": [],
        "Returned": [],
        "Failed": [],
        "Cancelled": [],
    }

    @classmethod
    def can_transition(cls, current_status: Optional[str], new_status: str) -> bool:
        return new_status in cls.VALID_TRANSITIONS.get(current_status, [])

    @classmethod
    def transition_payment_status(
        cls,
        db: Session,
        payment: Payment,
        new_status: str,
        notes: Optional[str] = None,
    ) -> bool:
        current_status = payment.status

        if not cls.can_transition(current_status, new_status):
            logger.error(
                "Invalid status transition for payment %s: %s -> %s",
                payment.id,
                current_status,
                new_status,
            )
            return False

        history = PaymentStatusHistory(
            transaction_id=payment.id,
            previous_status=current_status,
            new_status=new_status,
            timestamp=datetime.now(timezone.utc),
            notes=notes,
        )
        db.add(history)

        payment.status = new_status
        payment.updated_at = datetime.now(timezone.utc)

        if new_status == "Batched":
            payment.batched_at = datetime.now(timezone.utc)
        elif new_status == "Sent":
            payment.sent_at = datetime.now(timezone.utc)
        elif new_status == "Settled":
            payment.settled_at = datetime.now(timezone.utc)

        logger.info("Payment %s transitioned: %s -> %s", payment.id, current_status, new_status)
        return True


def emit_event(
    db: Session,
    event_type: EventType,
    transaction_id: str,
    payload: Optional[dict[str, JsonValue]] = None,
) -> None:
    event = PaymentEvent(
        event_type=event_type.value,
        transaction_id=transaction_id,
        payload=json.dumps(payload) if payload else None,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)

    logger.info(
        "Event emitted: %s for transaction %s",
        event_type.value,
        transaction_id,
        extra={"event_type": event_type.value, "transaction_id": transaction_id},
    )