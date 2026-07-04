from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from app.models import Payment

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


def generate_nacha_file(batch_id: str, payments: Iterable[Payment]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payment_list = list(payments)
    now = datetime.now(timezone.utc)
    file_date = now.strftime("%y%m%d")
    file_time = now.strftime("%H%M")
    file_name = OUTPUT_DIR / f"nacha_{now.strftime('%Y%m%d_%H%M%S')}.txt"

    file_header = (
        "1"
        + _fixed("01", 2)
        + _fixed("123456789", 10, "right")
        + _fixed("987654321", 10, "right")
        + file_date
        + file_time
        + "A"
        + "094"
        + "10"
        + "1"
        + _fixed("PAYMENT HUB", 23)
        + _fixed("SIMULATED BANK", 23)
        + _fixed("", 8)
    )

    batch_header = (
        "5"
        + "220"
        + _fixed("PAYMENT HUB", 16)
        + _fixed(batch_id.replace("-", "")[:20], 20)
        + _fixed("123456789", 10)
        + _fixed("PPD", 3)
        + _fixed("PAYMENTS", 10)
        + now.strftime("%y%m%d")
        + now.strftime("%y%m%d")
        + "   "
        + "1"
        + _fixed("12345678", 8)
        + "0000001"
    )

    entry_lines: list[str] = []
    total_amount = 0
    for index, payment in enumerate(payment_list, start=1):
        total_amount += int(round(payment.amount * 100))
        trace_number = f"12345678{str(index).rjust(7, '0')}"
        entry = (
            "6"
            + "22"
            + _fixed(payment.routing_number[:8], 8)
            + _fixed(payment.routing_number[8:], 1)
            + _fixed(payment.account_number, 17)
            + _amount_to_cents(payment.amount)
            + _fixed(payment.id.replace("-", "")[:15], 15)
            + _fixed(payment.payment_reason[:22], 22)
            + "0"
            + "0"
            + trace_number
        )
        entry_lines.append(entry)

    batch_control = (
        "8"
        + "220"
        + str(len(payment_list)).rjust(6, "0")
        + str(sum(int(payment.routing_number[:8]) for payment in payment_list)).rjust(10, "0")[-10:]
        + str(total_amount).rjust(12, "0")
        + str(total_amount).rjust(12, "0")
        + _fixed("123456789", 10)
        + _fixed("", 19)
        + _fixed("", 6)
        + _fixed("12345678", 8)
        + "0000001"
    )

    block_count = (len(entry_lines) + 4 + 9) // 10
    file_control = (
        "9"
        + "000001"
        + str(block_count).rjust(6, "0")
        + str(len(payment_list)).rjust(8, "0")
        + str(sum(int(payment.routing_number[:8]) for payment in payment_list)).rjust(10, "0")[-10:]
        + str(total_amount).rjust(12, "0")
        + str(total_amount).rjust(12, "0")
        + _fixed("", 39)
    )

    lines = [file_header, batch_header] + entry_lines + [batch_control, file_control]
    while len(lines) % 10 != 0:
        lines.append("9" * 94)

    _ = file_name.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return file_name

# Made with Bob
