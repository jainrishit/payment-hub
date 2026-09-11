# Payment Hub

A payment hub prototype that simulates the core lifecycle of ACH-style disbursement processing: intake, validation, batching, NACHA file generation, bank response handling, reconciliation, and auditability.

This prototype is designed to demonstrate payment-domain modeling, backend architecture, workflow design, and implementation discipline. It is intentionally built as a realistic simulation rather than a connection to a live banking network.

Real-world payment systems are more than CRUD applications. They must enforce lifecycle rules, preserve audit history, reconcile operational files, and provide traceability across internal and external events. Payment Hub models those concerns in a compact, explainable system suitable for architecture discussion, demos, and workflow exploration.

## How it works

This prototype walks through the full end-to-end lifecycle of an ACH-style payment, from creation through bank response. Each step below corresponds to a real stage in production payment systems.

**1. Payment creation**

New payments are submitted by internal users, such as insurance operations teams, through the dashboard or API. A payment represents a disbursement instruction, for example a claim payout, refund, or settlement. Each submission is validated against basic rules (ABA routing format, account number format, amount bounds) and stored with a status of `Requested`. Duplicate submissions are blocked via an idempotency key.

**2. Batch processing**

Payments are not sent to the bank individually. Instead, they are grouped into a batch during an end-of-day processing run. Batching is how real payment systems handle high volumes efficiently and how clearing networks expect instructions to arrive. When a batch runs, all eligible `Requested` payments are grouped, assigned a batch ID, and advanced to `Batched`.

**3. NACHA file generation**

After batching, the system generates a NACHA file. NACHA is the standardized fixed-width file format that ACH networks and banks actually understand. It encodes each payment as a structured entry record with routing and account details, amounts, and trace numbers, wrapped in batch and file control records. This file represents the real outbound instruction sent to the bank.

**4. Bank processing**

In a live environment, the NACHA file would be transmitted to the bank or ACH operator. Here it is simulated. The bank processes the file and determines an outcome for each payment entry: settled, returned due to an issue (such as an invalid account), or failed.

**5. Bank response handling (inbound)**

The bank sends back a response indicating the result of each payment. This inbound step is what closes the loop. In this prototype, the bank simulation endpoint handles this: it reads all `Sent` payments and applies realistic outcomes, advancing each to `Settled`, `Returned`, or `Failed`. Return codes (such as R02 for account closed or R10 for authorization revoked) are recorded against failed entries, mirroring how real ACH returns work.

**6. Audit trail**

Every status transition is recorded in an immutable history log, and business events are emitted at each stage. This gives operators full traceability: who created a payment, when it was batched, what the bank responded, and why it failed if it did.

## Business problem

Operations and finance teams need a reliable way to:
- accept payment requests
- validate account and routing details
- prevent duplicate submissions
- batch eligible transactions for outbound processing
- generate outbound payment files
- simulate downstream bank responses
- record status history and event logs for audit and support workflows

Payment Hub demonstrates how those responsibilities can be organized into a service-oriented application with a clean UI and API surface.

## What is simulated

This repository simulates several patterns found in real payment environments:
- request intake and validation
- idempotency protection
- payment lifecycle state management
- ACH/NACHA-style outbound file generation
- bank settlement / return / failure responses
- return codes and failure reasons
- immutable audit history
- operational dashboards for status tracking

This repository does **not** connect to a real bank, processor, clearing network, or customer data source.

## Payment lifecycle

```text
Requested
  ├─> Cancelled
  └─> Batched
        └─> Sent
              ├─> Settled
              ├─> Returned
              └─> Failed
```

### Lifecycle rules
- Payments begin in `Requested`
- Only `Requested` payments can be cancelled
- End-of-day batching moves eligible payments to `Batched`
- NACHA generation and dispatch simulation moves batched payments to `Sent`
- Bank simulation moves sent payments to `Settled`, `Returned`, or `Failed`
- Status changes are recorded in history and event logs

## Architecture overview

### Application layers
- **API layer**: FastAPI endpoints and HTML routes
- **Service layer**: payment orchestration, batching, event emission, bank simulation, NACHA generation
- **Persistence layer**: SQLAlchemy models with SQLite for local development
- **Presentation layer**: server-rendered dashboard and API documentation page

### Core domain objects
- `Payment`
- `Batch`
- `PaymentStatusHistory`
- `PaymentEvent`

### Key architectural characteristics
- typed SQLAlchemy models
- explicit state transition rules
- event and history tracking for auditability
- separation of validation, batching, simulation, and presentation concerns
- local-first development experience with minimal dependencies

For a deeper technical walkthrough, see [`SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md).

## Key features

- Full payment lifecycle management
- Idempotent payment creation
- ABA routing and account validation
- Batch generation and reconciliation
- NACHA file generation for simulated outbound processing
- Bank response simulation with realistic return-code scenarios
- Payment cancellation rules
- Status history and event log visibility
- Interactive dashboard for operators
- API documentation page for demo and testing

## Tech stack

- **Backend**: FastAPI
- **ORM**: SQLAlchemy 2.x
- **Validation**: Pydantic
- **Database**: SQLite (local/demo)
- **Frontend**: HTML, CSS, vanilla JavaScript
- **Server**: Uvicorn
- **Language**: Python 3.9+

## Running locally

### Prerequisites
- Python 3.9+
- pip

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m uvicorn app.main:app --reload
```

### Local URLs
- Dashboard: [`http://127.0.0.1:8000/`](http://127.0.0.1:8000/)
- API docs page: [`http://127.0.0.1:8000/api-docs`](http://127.0.0.1:8000/api-docs)

## Example API flow

### Create a payment

```bash
curl -X POST http://127.0.0.1:8000/payments \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mock-token" \
  -d '{
    "amount": 100.50,
    "routing_number": "021000021",
    "account_number": "987654321",
    "payment_reason": "claim",
    "idempotency_key": "demo-key-001"
  }'
```

### Run batch processing

```bash
curl -X POST http://127.0.0.1:8000/run-batch \
  -H "Authorization: Bearer mock-token"
```

### Simulate bank processing

```bash
curl -X POST http://127.0.0.1:8000/simulate-bank \
  -H "Authorization: Bearer mock-token"
```

### Inspect results

```bash
curl http://127.0.0.1:8000/payments \
  -H "Authorization: Bearer mock-token"
```

## API documentation access

The repository includes a custom documentation page exposed by the application at:
- [`http://127.0.0.1:8000/api-docs`](http://127.0.0.1:8000/api-docs)

## Repository structure

```text
app/
  main.py
  models.py
  database.py
  schemas.py
  services/
  templates/
  static/
batch/
simulation/
SYSTEM_ARCHITECTURE.md
requirements.txt
```

## Security and privacy notes

- Authentication is intentionally mocked with a demo bearer token for local use
- No live payment rails, processor credentials, or bank integrations are included
- SQLite is used only for local/demo persistence
- Generated files, logs, virtual environments, and local databases should not be committed

## Future enhancements

- Replace demo auth with OAuth2 or JWT-based authentication
- Add role-based access control and admin workflows
- Introduce PostgreSQL and migrations for production-style persistence
- Add automated tests and CI workflows
- Add metrics, tracing, and health endpoints
- Add asynchronous processing and queue-backed orchestration
- Add richer reconciliation and exception-handling workflows
- Add multi-rail behavior beyond the current ACH-oriented simulation

## License

Choose the license you want before publishing publicly. If you do not want reuse by default, keep the repository private or add a license intentionally.
