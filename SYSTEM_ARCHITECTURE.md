# Payment Hub - Enterprise Payment Processing System

## Overview

This is an enterprise-grade payment processing system built to demonstrate real-world payment hub architecture similar to SPS (Strategic Payment Systems). The system handles the complete payment lifecycle from creation through settlement, with full audit trails, event tracking, and multi-rail support.

## System Architecture

### Core Components

1. **Payment Lifecycle Engine** (`app/services/event_system.py`)
   - Manages strict state transitions
   - Enforces business rules
   - Maintains audit trail
   - Prevents invalid state changes

2. **Validation Layer** (`app/services/validation.py`)
   - Routing number validation (ABA checksum)
   - Account number format validation
   - Amount validation
   - Payment reason validation
   - Duplicate detection

3. **Event System** (`app/services/event_system.py`)
   - Event-driven architecture
   - Persistent event log
   - Event types: PAYMENT_CREATED, PAYMENT_VALIDATED, PAYMENT_BATCHED, PAYMENT_SENT, PAYMENT_SETTLED, PAYMENT_RETURNED, PAYMENT_FAILED, PAYMENT_CANCELLED, BATCH_CREATED, BATCH_PROCESSED
   - Full traceability

4. **Payment Processor Architecture** (`app/services/payment_processor.py`)
   - Extensible multi-rail design
   - Abstract base class for processors
   - Implementations: ACH, Wire, Check
   - Easy to add new payment rails

5. **Batch Processing Engine** (`app/services/batch_service.py`)
   - Automatic payment extraction
   - Batch creation and management
   - NACHA file generation
   - Reconciliation and validation

6. **Bank Simulator** (`app/services/bank_simulator.py`)
   - Realistic ACH return codes (R01-R29)
   - Randomized outcome simulation: Settled (majority), Returned (some), Failed (few)
   - Failure reason tracking
   - Response file generation

## Payment Lifecycle

```
REQUESTED → BATCHED → SENT → SETTLED
    ↓                       → RETURNED
CANCELLED                   → FAILED
```

### State Transitions

- **Requested**: Initial state after validation
- **Batched**: Payment added to batch for processing
- **Sent**: Payment sent to bank via NACHA file
- **Settled**: Successfully processed by bank
- **Returned**: Rejected by bank with return code
- **Failed**: Processing failure
- **Cancelled**: Payment cancelled by user (only from Requested)

### Transition Rules

- **Requested** → Batched, Failed, Cancelled
- **Batched** → Sent, Failed
- **Sent** → Settled, Returned, Failed
- **Settled, Returned, Failed, Cancelled** → Terminal states (no further transitions)
- All transitions are logged in status history
- Timestamps recorded for each stage

### Immutability Rules

- Payments can only be cancelled while in **Requested** status
- Once **Batched** or **Sent**, payments cannot be modified or cancelled
- This enforces payment integrity and maintains audit compliance

## Database Schema

### Tables

1. **payments**
   - Core payment data
   - Status tracking
   - Lifecycle timestamps (created_at, batched_at, sent_at, settled_at)
   - Return codes and failure reasons
   - Batch association

2. **payment_status_history**
   - Complete audit trail
   - Previous and new status
   - Transition timestamps
   - Notes for each transition

3. **payment_events**
   - Event log
   - Event type and payload
   - Transaction association
   - Timestamp tracking

4. **batches**
   - Batch metadata
   - Transaction counts and totals
   - NACHA file path
   - Processing timestamps

## API Endpoints

### Payment Operations

- `POST /payments` - Create new payment with validation
- `GET /payments` - List payments with optional status filter
- `GET /payments/{id}` - Get payment details
- `GET /payments/{id}/history` - Get status history
- `GET /payments/{id}/events` - Get event log
- `POST /payments/{id}/cancel` - Cancel payment (only allowed when status is 'Requested')

### Batch Operations

- `POST /run-batch` - Execute end-of-day batch processing
- `GET /batches` - List recent batches

### Bank Simulation

- `POST /simulate-bank` - Simulate bank processing with realistic outcomes

### File Operations

- `GET /nacha-file` - Retrieve latest NACHA file

## Validation Rules

### Routing Number
- Must be exactly 9 digits
- Must pass ABA checksum algorithm
- Format: XXXXYYYYC (X=Federal Reserve routing, Y=ABA institution, C=check digit)

### Account Number
- 1-17 digits
- Numeric only

### Amount
- Greater than $0
- Maximum $10,000,000
- Maximum 2 decimal places

### Payment Reason
- Must be one of: claim, refund, settlement, disbursement, commission, payroll

## ACH Return Codes

The system simulates realistic ACH return codes:

- **R01**: Insufficient Funds
- **R02**: Account Closed
- **R03**: No Account/Unable to Locate Account
- **R04**: Invalid Account Number
- **R05**: Unauthorized Debit
- **R07**: Authorization Revoked
- **R08**: Payment Stopped
- **R09**: Uncollected Funds
- **R10**: Customer Advises Not Authorized
- **R14**: Representative Payee Deceased
- **R15**: Beneficiary Deceased
- **R16**: Account Frozen
- **R20**: Non-Transaction Account
- **R29**: Corporate Customer Advises Not Authorized

## NACHA File Format

Generated files follow NACHA (National Automated Clearing House Association) format:

1. **File Header** (Record Type 1)
2. **Batch Header** (Record Type 5)
3. **Entry Detail Records** (Record Type 6)
4. **Batch Control** (Record Type 8)
5. **File Control** (Record Type 9)
6. **Padding** (Record Type 9, filler)

**Note**: NACHA files generated in this system are structurally accurate representations used for simulation purposes. In production systems, NACHA files require strict validation, bank-specific configurations, secure transmission protocols, and comprehensive compliance checks before being accepted by financial institutions.

## Logging and Traceability

### Structured Logging
- All operations logged with context
- Transaction IDs for correlation
- Timestamps for all events
- Error tracking with stack traces

### Audit Trail
- Complete status history
- Event log for all actions
- Immutable records
- Timestamp precision

## Extensibility

### Adding New Payment Rails

1. Create new processor class extending `PaymentProcessor`
2. Implement required methods:
   - `process_payment()`
   - `validate_payment()`
   - `get_rail_name()`
3. Register in `PaymentProcessorFactory`

Example:
```python
class RTPProcessor(PaymentProcessor):
    def get_rail_name(self) -> str:
        return "RTP"
    
    def validate_payment(self, payment: Payment) -> tuple[bool, Optional[str]]:
        # RTP-specific validation
        return True, None
    
    def process_payment(self, payment: Payment) -> bool:
        # RTP processing logic
        return True
```

## Security

- Bearer token authentication
- Input validation on all endpoints
- SQL injection prevention (SQLAlchemy ORM)
- Idempotency key enforcement
- Duplicate detection

## Performance Considerations

- Database indexing on key fields (status, batch_id, idempotency_key)
- Batch processing for efficiency
- Query optimization with filters
- Connection pooling

## Monitoring and Observability

### Key Metrics
- Payment volume by status (including Cancelled)
- Batch processing time
- Settlement success rate
- Return rate by code
- Processing errors
- Cancellation rate

### Health Checks
- Database connectivity
- File system access
- API responsiveness

## Development Notes

### Built with AI-Driven Development

This system was developed using prompt-driven workflow with Claude (Anthropic). The architecture demonstrates:

- Enterprise design patterns
- Real-world payment processing concepts
- Extensible and maintainable code structure
- Production-ready error handling
- Comprehensive logging and audit trails

### Technology Stack

- **Framework**: FastAPI 0.115.0
- **Database**: SQLite with SQLAlchemy 2.0.35
- **Validation**: Pydantic 1.10.18
- **Server**: Uvicorn 0.30.6
- **Language**: Python 3.9+

## Future Enhancements

1. **Real-time Processing**
   - WebSocket support for live updates
   - Push notifications for status changes

2. **Advanced Reporting**
   - Analytics dashboard
   - Reconciliation reports
   - Compliance reporting

3. **Multi-tenancy**
   - Organization isolation
   - Role-based access control

4. **Integration**
   - Real bank connectivity
   - Third-party payment rails
   - Webhook support

5. **Scalability**
   - PostgreSQL migration
   - Redis caching
   - Message queue integration
   - Horizontal scaling

## Conclusion

This Payment Hub demonstrates a production-ready payment processing system with enterprise-grade features including full lifecycle management, audit trails, event-driven architecture, and extensible design. The system can serve as a foundation for real-world payment processing applications.

---

**Built with Bob - AI-Powered Development**