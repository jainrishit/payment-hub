from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

from typing_extensions import TypedDict

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models import Base, Batch
from app.schemas import PaymentCreate, PaymentListResponse, PaymentResponse
from app.services.bank_simulator import simulate_bank_processing
from app.services.batch_service import process_end_of_day_batch
from app.services.nacha_generator import OUTPUT_DIR as NACHA_OUTPUT_DIR
from app.services.payment_service import (
    EventResponse,
    HistoryResponse,
    PaymentResponseDict,
    cancel_payment,
    create_payment,
    get_payment_by_id,
    get_payment_events,
    get_payment_history,
    list_payments,
)

SAMPLE_PAYMENTS = [
    {
        "amount": 2500.00,
        "routing_number": "021000021",
        "account_number": "123456789",
        "payment_reason": "Auto Claim Settlement",
        "idempotency_key": "demo-auto-claim-001",
    },
    {
        "amount": 175.00,
        "routing_number": "026009593",
        "account_number": "987654321",
        "payment_reason": "Premium Refund",
        "idempotency_key": "demo-premium-refund-001",
    },
    {
        "amount": 8250.00,
        "routing_number": "011000015",
        "account_number": "456789123",
        "payment_reason": "Property Damage Claim",
        "idempotency_key": "demo-property-damage-001",
    },
    {
        "amount": 620.00,
        "routing_number": "021000021",
        "account_number": "567891234",
        "payment_reason": "Medical Expense Reimbursement",
        "idempotency_key": "demo-medical-reimb-001",
    },
    {
        "amount": 1850.00,
        "routing_number": "026009593",
        "account_number": "678912345",
        "payment_reason": "Disability Benefit",
        "idempotency_key": "demo-disability-benefit-001",
    },
    {
        "amount": 12500.00,
        "routing_number": "011000015",
        "account_number": "789123456",
        "payment_reason": "Catastrophe Claim Settlement",
        "idempotency_key": "demo-catastrophe-claim-001",
    },
]


class SuccessEnvelope(TypedDict):
    success: bool
    message: str
    data: object


class PaymentHistoryEnvelope(TypedDict):
    payment_id: str
    history: list[HistoryResponse]


class PaymentEventsEnvelope(TypedDict):
    payment_id: str
    events: list[EventResponse]


class NachaFileResponse(TypedDict):
    filename: str
    content: str
    created_at: str


class BatchSummary(TypedDict):
    batch_id: str
    transaction_count: int
    total_amount: float
    status: str
    created_at: str


class BatchListResponse(TypedDict):
    batches: list[BatchSummary]


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Payment Hub Prototype", version="1.0.0")
# Use absolute paths so the app works correctly inside Vercel's serverless environment.
_APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))

static_dir = _APP_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def authorize_request(authorization: Annotated[str, Header()] = "") -> None:
    if authorization != "Bearer mock-token":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized request")


@app.post("/payments", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(authorize_request)])
def create_payment_endpoint(payload: PaymentCreate, db: Annotated[Session, Depends(get_db)]) -> PaymentResponseDict:
    return create_payment(db, payload)


@app.get("/payments/{payment_id}", response_model=PaymentResponse, dependencies=[Depends(authorize_request)])
def get_payment_endpoint(payment_id: str, db: Annotated[Session, Depends(get_db)]) -> PaymentResponseDict:
    payment = get_payment_by_id(db, payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return payment


@app.get("/payments", response_model=PaymentListResponse, dependencies=[Depends(authorize_request)])
def list_payments_endpoint(
    db: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[Optional[str], Query(alias="status")] = None,
) -> PaymentListResponse:
    payments: list[PaymentResponse] = []
    for payment in list_payments(db, status_filter=status_filter):
        payments.append(
            PaymentResponse(
                transaction_id=payment["transaction_id"],
                status=payment["status"],
                amount=payment["amount"],
                routing_number=payment["routing_number"],
                account_number=payment["account_number"],
                payment_reason=payment["payment_reason"],
                batch_id=payment["batch_id"],
                created_at=payment["created_at"],
                updated_at=payment["updated_at"],
            )
        )
    return PaymentListResponse(payments=payments)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api-docs", response_class=HTMLResponse)
def api_documentation(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("api_docs.html", {"request": request})


@app.post("/run-batch", dependencies=[Depends(authorize_request)])
def run_batch_endpoint(db: Annotated[Session, Depends(get_db)]) -> SuccessEnvelope:
    try:
        result = process_end_of_day_batch(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error running batch: {exc}") from exc
    return {"success": True, "message": result["message"], "data": result}


@app.post("/simulate-bank", dependencies=[Depends(authorize_request)])
def simulate_bank_endpoint(db: Annotated[Session, Depends(get_db)]) -> SuccessEnvelope:
    try:
        result = simulate_bank_processing(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error simulating bank: {exc}") from exc
    return {"success": True, "message": result["message"], "data": result}


@app.post("/process-inbound", dependencies=[Depends(authorize_request)])
def process_inbound_endpoint() -> dict[str, object]:
    return {"success": True, "message": "Inbound processing handled by bank simulation"}


@app.get("/payments/{payment_id}/history", dependencies=[Depends(authorize_request)])
def get_payment_history_endpoint(payment_id: str, db: Annotated[Session, Depends(get_db)]) -> PaymentHistoryEnvelope:
    history = get_payment_history(db, payment_id)
    if not history:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"payment_id": payment_id, "history": history}


@app.get("/payments/{payment_id}/events", dependencies=[Depends(authorize_request)])
def get_payment_events_endpoint(payment_id: str, db: Annotated[Session, Depends(get_db)]) -> PaymentEventsEnvelope:
    events = get_payment_events(db, payment_id)
    if not events:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"payment_id": payment_id, "events": events}


@app.post("/payments/{payment_id}/cancel", dependencies=[Depends(authorize_request)])
def cancel_payment_endpoint(payment_id: str, db: Annotated[Session, Depends(get_db)]) -> PaymentResponseDict:
    return cancel_payment(db, payment_id)


@app.get("/nacha-file", dependencies=[Depends(authorize_request)])
def get_nacha_file() -> NachaFileResponse:
    output_dir = NACHA_OUTPUT_DIR
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="Output directory not found")

    nacha_files = sorted(output_dir.glob("nacha_*.txt"), key=lambda file_path: file_path.stat().st_mtime, reverse=True)
    if not nacha_files:
        raise HTTPException(status_code=404, detail="No NACHA file found")

    latest_file = nacha_files[0]
    return {
        "filename": latest_file.name,
        "content": latest_file.read_text(encoding="utf-8"),
        "created_at": datetime.fromtimestamp(latest_file.stat().st_mtime, tz=timezone.utc).isoformat(),
    }


@app.post("/load-samples", dependencies=[Depends(authorize_request)])
def load_sample_payments(db: Annotated[Session, Depends(get_db)]) -> SuccessEnvelope:
    """Load realistic insurance sample payments for demo purposes."""
    created = 0
    skipped = 0
    for sample in SAMPLE_PAYMENTS:
        try:
            create_payment(db, PaymentCreate(**sample))
            created += 1
        except Exception:
            skipped += 1
    if created == 0:
        return {
            "success": True,
            "message": f"Sample payments already loaded ({skipped} skipped — idempotency keys already exist). Reset the database to reload.",
            "data": {"created": 0, "skipped": skipped},
        }
    return {
        "success": True,
        "message": f"{created} sample insurance payments created successfully.",
        "data": {"created": created, "skipped": skipped},
    }


@app.get("/batches", dependencies=[Depends(authorize_request)])
def get_batches(db: Annotated[Session, Depends(get_db)]) -> BatchListResponse:
    batches = db.query(Batch).order_by(Batch.created_at.desc()).limit(10).all()
    batch_list: list[BatchSummary] = []
    for batch in batches:
        batch_list.append(
            {
                "batch_id": batch.batch_id,
                "transaction_count": batch.total_transactions,
                "total_amount": batch.total_amount,
                "status": batch.status,
                "created_at": batch.created_at.isoformat(),
            }
        )
    return {"batches": batch_list}
