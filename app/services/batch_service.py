import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TypedDict

from sqlalchemy.orm import Session

from app.models import Batch, Payment
from app.services.event_system import EventType, PaymentLifecycleEngine, emit_event
from app.services.nacha_generator import generate_nacha_file

logger = logging.getLogger(__name__)


class BatchResult(TypedDict):
    message: str
    batch_id: Optional[str]
    file_path: Optional[str]
    total_transactions: int
    total_amount: float


def _sum_payment_amounts(payments: list[Payment]) -> float:
    return round(sum(payment.amount for payment in payments), 2)


def process_end_of_day_batch(db: Session) -> BatchResult:
    """Process end-of-day batch for requested payments."""
    requested_payments = (
        db.query(Payment)
        .filter(Payment.status == "Requested")
        .filter(Payment.extracted_for_batch.is_(False))
        .with_for_update()
        .order_by(Payment.created_at.asc())
        .all()
    )

    if not requested_payments:
        logger.info("No requested payments available for batching")
        return {
            "message": "No requested payments available",
            "batch_id": None,
            "file_path": None,
            "total_transactions": 0,
            "total_amount": 0.0,
        }

    batch_id = str(uuid.uuid4())
    total_transactions = len(requested_payments)
    total_amount = _sum_payment_amounts(requested_payments)

    logger.info(
        "Starting batch processing batch_id=%s total_transactions=%s total_amount=%s",
        batch_id,
        total_transactions,
        total_amount,
    )

    emit_event(
        db,
        EventType.BATCH_CREATED,
        requested_payments[0].id,
        {
            "batch_id": batch_id,
            "total_transactions": total_transactions,
            "total_amount": total_amount,
        },
    )

    for payment in requested_payments:
        payment.batch_id = batch_id
        payment.extracted_for_batch = True
        success = PaymentLifecycleEngine.transition_payment_status(
            db,
            payment,
            "Batched",
            f"Payment added to batch {batch_id}",
        )
        if success:
            emit_event(
                db,
                EventType.PAYMENT_BATCHED,
                payment.id,
                {"batch_id": batch_id},
            )

    db.flush()

    nacha_path = generate_nacha_file(batch_id, requested_payments)
    if not Path(nacha_path).exists():
        logger.error("NACHA file generation failed for batch_id=%s", batch_id)
        raise RuntimeError("NACHA file generation failed")

    generated_count = len(requested_payments)
    generated_amount = _sum_payment_amounts(requested_payments)
    if generated_count != total_transactions or generated_amount != total_amount:
        logger.error(
            "Batch reconciliation mismatch batch_id=%s expected_count=%s actual_count=%s expected_amount=%s actual_amount=%s",
            batch_id,
            total_transactions,
            generated_count,
            total_amount,
            generated_amount,
        )
        raise RuntimeError("Batch reconciliation mismatch")

    db.add(
        Batch(
            batch_id=batch_id,
            total_transactions=total_transactions,
            total_amount=total_amount,
            status="Sent",
            nacha_file_path=str(nacha_path),
            processed_at=datetime.now(timezone.utc),
        )
    )

    for payment in requested_payments:
        success = PaymentLifecycleEngine.transition_payment_status(
            db,
            payment,
            "Sent",
            f"Payment sent in batch {batch_id}",
        )
        if success:
            emit_event(
                db,
                EventType.PAYMENT_SENT,
                payment.id,
                {"batch_id": batch_id, "nacha_file": str(nacha_path)},
            )

    emit_event(
        db,
        EventType.BATCH_PROCESSED,
        requested_payments[0].id,
        {
            "batch_id": batch_id,
            "nacha_file": str(nacha_path),
            "total_transactions": total_transactions,
            "total_amount": total_amount,
        },
    )

    db.commit()
    logger.info("Batch completed successfully batch_id=%s file=%s", batch_id, nacha_path)
    return {
        "message": "Batch processed successfully",
        "batch_id": batch_id,
        "file_path": str(nacha_path),
        "total_transactions": total_transactions,
        "total_amount": total_amount,
    }
