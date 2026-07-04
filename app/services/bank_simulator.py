import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TypedDict

from sqlalchemy.orm import Session

from app.models import Payment
from app.services.event_system import EventType, PaymentLifecycleEngine, emit_event

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "output"

RETURN_CODES = {
    "R01": "Insufficient Funds",
    "R02": "Account Closed",
    "R03": "No Account/Unable to Locate Account",
    "R04": "Invalid Account Number",
    "R05": "Unauthorized Debit to Consumer Account",
    "R07": "Authorization Revoked by Customer",
    "R08": "Payment Stopped",
    "R09": "Uncollected Funds",
    "R10": "Customer Advises Not Authorized",
    "R14": "Representative Payee Deceased or Unable to Continue",
    "R15": "Beneficiary or Account Holder Deceased",
    "R16": "Account Frozen",
    "R20": "Non-Transaction Account",
    "R29": "Corporate Customer Advises Not Authorized",
}


class SimulationResult(TypedDict):
    transaction_id: str
    status: str
    return_code: Optional[str]
    failure_reason: Optional[str]


class BankSimulationResult(TypedDict):
    message: str
    response_file: Optional[str]
    total: int
    settled: int
    returned: int
    failed: int


class BankResponseFile(TypedDict):
    processed_at: str
    nacha_file: str
    summary: dict[str, int]
    results: list[SimulationResult]


def _latest_nacha_file() -> Path:
    files = sorted(OUTPUT_DIR.glob("nacha_*.txt"))
    if not files:
        raise FileNotFoundError("No NACHA files found in output directory")
    return files[-1]


def _get_random_return_code() -> tuple[str, str]:
    code = random.choice(list(RETURN_CODES.keys()))
    return code, RETURN_CODES[code]


def simulate_bank_processing(db: Session) -> BankSimulationResult:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        nacha_file = _latest_nacha_file()
    except FileNotFoundError as exc:
        logger.error("No NACHA file found: %s", exc)
        return {
            "message": "No NACHA file found",
            "response_file": None,
            "total": 0,
            "settled": 0,
            "returned": 0,
            "failed": 0,
        }

    sent_payments = (
        db.query(Payment)
        .filter(Payment.status == "Sent")
        .order_by(Payment.created_at.asc())
        .all()
    )
    if not sent_payments:
        logger.info("No sent payments available for bank simulation")
        return {
            "message": "No sent payments available",
            "response_file": None,
            "total": 0,
            "settled": 0,
            "returned": 0,
            "failed": 0,
        }

    logger.info("Simulating bank processing using file=%s for %d payments", nacha_file, len(sent_payments))

    results: list[SimulationResult] = []
    settled_count = 0
    returned_count = 0
    failed_count = 0

    for payment in sent_payments:
        outcome = random.choices(["Settled", "Returned", "Failed"], weights=[0.85, 0.12, 0.03], k=1)[0]

        if outcome == "Settled":
            success = PaymentLifecycleEngine.transition_payment_status(
                db,
                payment,
                "Settled",
                "Payment settled successfully by bank",
            )
            if success:
                emit_event(db, EventType.PAYMENT_SETTLED, payment.id, {"amount": payment.amount})
                settled_count += 1
            results.append(
                {
                    "transaction_id": payment.id,
                    "status": "Settled",
                    "return_code": None,
                    "failure_reason": None,
                }
            )
        elif outcome == "Returned":
            return_code, failure_reason = _get_random_return_code()
            payment.return_code = return_code
            payment.failure_reason = failure_reason
            success = PaymentLifecycleEngine.transition_payment_status(
                db,
                payment,
                "Returned",
                f"Payment returned by bank: {return_code} - {failure_reason}",
            )
            if success:
                emit_event(
                    db,
                    EventType.PAYMENT_RETURNED,
                    payment.id,
                    {
                        "return_code": return_code,
                        "failure_reason": failure_reason,
                        "amount": payment.amount,
                    },
                )
                returned_count += 1
            results.append(
                {
                    "transaction_id": payment.id,
                    "status": "Returned",
                    "return_code": return_code,
                    "failure_reason": failure_reason,
                }
            )
        else:
            failure_reason = random.choice([
                "Network timeout",
                "Processing error",
                "System unavailable",
                "Invalid format",
            ])
            payment.failure_reason = failure_reason
            success = PaymentLifecycleEngine.transition_payment_status(
                db,
                payment,
                "Failed",
                f"Payment processing failed: {failure_reason}",
            )
            if success:
                emit_event(
                    db,
                    EventType.PAYMENT_FAILED,
                    payment.id,
                    {"failure_reason": failure_reason, "amount": payment.amount},
                )
                failed_count += 1
            results.append(
                {
                    "transaction_id": payment.id,
                    "status": "Failed",
                    "return_code": None,
                    "failure_reason": failure_reason,
                }
            )

        logger.info(
            "Payment %s processed: %s (return_code=%s, reason=%s)",
            payment.id,
            outcome,
            payment.return_code if outcome == "Returned" else "N/A",
            payment.failure_reason if outcome in {"Returned", "Failed"} else "N/A",
        )

    db.commit()

    response_file = OUTPUT_DIR / f"bank_response_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    response_data: BankResponseFile = {
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "nacha_file": str(nacha_file),
        "summary": {
            "total": len(results),
            "settled": settled_count,
            "returned": returned_count,
            "failed": failed_count,
        },
        "results": results,
    }
    _ = response_file.write_text(json.dumps(response_data, indent=2), encoding="utf-8")

    logger.info(
        "Bank response file created file=%s total=%d settled=%d returned=%d failed=%d",
        response_file,
        len(results),
        settled_count,
        returned_count,
        failed_count,
    )
    return {
        "message": "Bank simulation completed",
        "response_file": str(response_file),
        "total": len(results),
        "settled": settled_count,
        "returned": returned_count,
        "failed": failed_count,
    }
