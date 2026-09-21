import os
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from app.models import Payment

# On Vercel the filesystem is read-only except /tmp; write output there.
if os.environ.get("VERCEL"):
    OUTPUT_DIR = Path("/tmp/output")
else:
    OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "output"


def _fixed(value: str, length: int, align: str = "left", fill: str = " ") -> str:
    text = str(value)
    if len(text) > length:
        text = text[:length]
    if align == "right":
        return text.rjust(length, fill)
    return text.ljust(length, fill)


def _amount_to_cents(amount: float) -> str:
    cents = int(round(amount * 100))
    return str(cents).rjust(10, "0")


# Simulated ODFI routing prefix (8-digit) and full 9-digit routing number
_ODFI_ROUTING_PREFIX = "12345678"
_ODFI_ROUTING = "123456789"
# Simulated immediate destination (Federal Reserve routing)
_FED_ROUTING = "987654321"
# Originator company name (max 16 chars for batch header, 23 for file header)
_COMPANY_NAME_16 = "PAYMENT HUB     "
_COMPANY_NAME_23 = "PAYMENT HUB            "
_DEST_NAME_23   = "SIMULATED BANK         "


def _batch_number_from_id(batch_id: str) -> str:
    """Derive a stable 7-digit batch sequence number from the batch UUID."""
    # Use last 7 hex digits of UUID, converted to decimal, modulo 9999999
    hex_tail = batch_id.replace("-", "")[-7:]
    return str(int(hex_tail, 16) % 9_999_999 + 1).rjust(7, "0")


def generate_nacha_file(batch_id: str, payments: Iterable[Payment]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payment_list = list(payments)
    now = datetime.now(timezone.utc)
    file_date = now.strftime("%y%m%d")
    file_time = now.strftime("%H%M")
    file_name = OUTPUT_DIR / f"nacha_{now.strftime('%Y%m%d_%H%M%S')}.txt"

    batch_num = _batch_number_from_id(batch_id)

    # --- File Header (Record Type 1) — 94 characters ---
    # Priority code 01, immediate destination (right-justified with leading space),
    # immediate origin (right-justified), file creation date/time, blocking factor,
    # format code, immediate destination name, immediate origin name, reference code.
    file_header = (
        "1"                                          # record type
        + "01"                                       # priority code
        + _fixed(" " + _FED_ROUTING, 10)            # immediate destination (space + 9-digit routing)
        + _fixed(_ODFI_ROUTING, 10, "right")         # immediate origin (right-justified)
        + file_date                                  # 6-digit creation date YYMMDD
        + file_time                                  # 4-digit creation time HHMM
        + "A"                                        # file ID modifier
        + "094"                                      # record size (94 bytes)
        + "10"                                       # blocking factor (10 records per block)
        + "1"                                        # format code
        + _fixed("SIMULATED BANK", 23)               # immediate destination name
        + _fixed("PAYMENT HUB", 23)                  # immediate origin name
        + _fixed("", 8)                              # reference code (blank)
    )

    # --- Batch Header (Record Type 5) — 94 characters ---
    # Service class 220 = credits only, company name, company discretionary data,
    # company ID (tax ID / EIN), SEC code PPD, effective entry date, batch number.
    batch_header = (
        "5"                                          # record type
        + "220"                                      # service class code (credits only)
        + _fixed("PAYMENT HUB", 16)                 # company name
        + _fixed(batch_id.replace("-", "")[:20], 20) # company discretionary data
        + _fixed(_ODFI_ROUTING, 10)                  # company identification (ODFI routing)
        + "PPD"                                      # SEC code
        + _fixed("PAYMENTS", 10)                     # company entry description
        + now.strftime("%y%m%d")                     # descriptive date (YYMMDD)
        + now.strftime("%y%m%d")                     # effective entry date (YYMMDD)
        + "   "                                      # settlement date (filled by Fed)
        + "1"                                        # originator status code
        + _ODFI_ROUTING_PREFIX                       # ODFI routing prefix (8 digits)
        + batch_num                                  # batch number (7 digits, unique per batch)
    )

    # --- Entry Detail Records (Record Type 6) — 94 characters each ---
    entry_lines: list[str] = []
    total_credit_cents = 0
    for index, payment in enumerate(payment_list, start=1):
        total_credit_cents += int(round(payment.amount * 100))
        # Trace number = ODFI 8-digit prefix + 7-digit sequence within batch
        trace_number = _ODFI_ROUTING_PREFIX + str(index).rjust(7, "0")
        entry = (
            "6"                                      # record type
            + "22"                                   # transaction code: checking account credit
            + _fixed(payment.routing_number[:8], 8)  # RDFI routing transit (8 digits)
            + payment.routing_number[8]              # check digit (1 digit)
            + _fixed(payment.account_number, 17)     # RDFI account number (17 chars, left-justified)
            + _amount_to_cents(payment.amount)       # amount in cents (10 digits)
            + _fixed(payment.id.replace("-", "")[:15], 15)  # individual identification number
            + _fixed(payment.payment_reason[:22], 22)        # individual name (22 chars)
            + "  "                                   # discretionary data (2 chars, blank)
            + "0"                                    # addenda record indicator (no addenda)
            + trace_number                           # trace number (15 digits)
        )
        entry_lines.append(entry)

    # Entry hash = sum of 8-digit RDFI routing prefixes (rightmost 10 digits if overflow)
    entry_hash = str(
        sum(int(p.routing_number[:8]) for p in payment_list)
    ).rjust(10, "0")[-10:]

    # --- Batch Control (Record Type 8) — 94 characters ---
    # Service class must match batch header (220).
    # Debit total = 000000000000 (no debits in a credit-only PPD batch).
    # Credit total = sum of all entry amounts in cents.
    batch_control = (
        "8"                                          # record type
        + "220"                                      # service class code (must match batch header)
        + str(len(payment_list)).rjust(6, "0")       # entry/addenda count
        + entry_hash                                 # entry hash (sum of RDFI routing prefixes)
        + "000000000000"                             # total debit amount (zero — credits only)
        + str(total_credit_cents).rjust(12, "0")     # total credit amount in cents
        + _fixed(_ODFI_ROUTING, 10)                  # company identification
        + _fixed("", 25)                             # message authentication code (blank)
        + _fixed(_ODFI_ROUTING_PREFIX, 8)            # ODFI routing prefix
        + batch_num                                  # batch number (must match batch header)
    )

    # Number of physical 10-record blocks needed to hold all records
    # Records = 1 (file header) + 1 (batch header) + N (entries) + 1 (batch control) + 1 (file control)
    total_records = 2 + len(entry_lines) + 2  # file header + batch header + entries + batch ctrl + file ctrl
    block_count = (total_records + 9) // 10

    # --- File Control (Record Type 9) — 94 characters ---
    # Batch count = 1 (this generator always produces one batch per file).
    # Block count = number of 10-record blocks (including padding).
    # Entry/addenda count, hash, and totals mirror the single batch.
    file_control = (
        "9"                                          # record type
        + "000001"                                   # batch count (1 batch per file)
        + str(block_count).rjust(6, "0")             # block count
        + str(len(payment_list)).rjust(8, "0")       # entry/addenda count
        + entry_hash                                 # entry hash (same as batch control)
        + "000000000000"                             # total debit amount (zero — credits only)
        + str(total_credit_cents).rjust(12, "0")     # total credit amount in cents
        + _fixed("", 39)                             # reserved (blank)
    )

    lines = [file_header, batch_header] + entry_lines + [batch_control, file_control]

    # Pad to a full block boundary with 9-filled records (94 nines each)
    while len(lines) % 10 != 0:
        lines.append("9" * 94)

    # Sanity-check: every record must be exactly 94 characters
    for i, line in enumerate(lines):
        if len(line) != 94:
            raise ValueError(f"NACHA record {i} has length {len(line)}, expected 94")

    _ = file_name.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return file_name

# Made with Bob
