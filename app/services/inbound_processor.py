# pyright: reportAny=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportAttributeAccessIssue=false

import json
import logging
from pathlib import Path

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.models import Payment

logger = logging.getLogger(__name__)

class InboundResult(BaseModel):
    transaction_id: str
    status: str


class InboundPayload(BaseModel):
    results: list[InboundResult]


OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "output"


def _latest_response_file() -> Path:
    files = sorted(OUTPUT_DIR.glob("bank_response_*.json"))
    if not files:
        raise FileNotFoundError("No bank response files found in output directory")
    return files[-1]


def process_inbound_file(db: Session) -> dict[str, object]:
    response_file = _latest_response_file()
    payload_data = json.loads(response_file.read_text(encoding="utf-8"))
    try:
        payload = InboundPayload.model_validate(payload_data)
    except ValidationError as exc:
        raise ValueError("Invalid bank response payload") from exc

    updated = 0
    unmatched: list[str] = []

    for record in payload.results:
        transaction_id = record.transaction_id
        new_status = record.status
        payment = db.query(Payment).filter(Payment.id == transaction_id).first()

        if payment is None:
            logger.error("Inbound unmatched transaction_id=%s", transaction_id)
            unmatched.append(transaction_id)
            continue

        if payment.status != "Sent":
            logger.error(
                "Inbound status transition rejected transaction_id=%s current_status=%s target_status=%s",
                transaction_id,
                payment.status,
                new_status,
            )
            unmatched.append(transaction_id)
            continue

        if new_status not in {"Settled", "Returned"}:
            logger.error("Inbound invalid status transaction_id=%s status=%s", transaction_id, new_status)
            unmatched.append(transaction_id)
            continue

        payment.status = new_status
        updated += 1

    db.commit()

    logger.info(
        "Inbound processing completed file=%s updated=%s unmatched=%s",
        response_file,
        updated,
        len(unmatched),
    )
    return {
        "message": "Inbound processing completed",
        "response_file": str(response_file),
        "updated": updated,
        "unmatched": unmatched,
    }

# Made with Bob
