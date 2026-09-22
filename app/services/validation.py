import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def validate_routing_number(routing_number: str) -> tuple[bool, Optional[str]]:
    """
    Validate routing number using ABA checksum algorithm.
    Returns (is_valid, error_message)
    """
    if not routing_number or len(routing_number) != 9:
        return False, "Routing number must be exactly 9 digits"

    if not routing_number.isdigit():
        return False, "Routing number must contain only digits"

    # ABA checksum: 3*(d0+d3+d6) + 7*(d1+d4+d7) + (d2+d5+d8) must be divisible by 10
    try:
        digits = [int(d) for d in routing_number]
        checksum = (
            3 * (digits[0] + digits[3] + digits[6]) +
            7 * (digits[1] + digits[4] + digits[7]) +
            (digits[2] + digits[5] + digits[8])
        )

        if checksum % 10 != 0:
            return False, "Please enter a valid 9-digit ABA routing number"

        return True, None
    except Exception as e:
        logger.error(f"Routing number validation error: {e}")
        return False, "Please enter a valid 9-digit ABA routing number"


def validate_account_number(account_number: str) -> tuple[bool, Optional[str]]:
    """
    Validate account number format.
    Returns (is_valid, error_message)
    """
    if not account_number:
        return False, "Account number is required"
    
    if not re.match(r'^[0-9]{8,17}$', account_number):
        return False, "Account number must be between 8 and 17 digits"
    
    return True, None


def validate_amount(amount: float) -> tuple[bool, Optional[str]]:
    """
    Validate payment amount.
    Returns (is_valid, error_message)
    """
    if amount <= 0:
        return False, "Amount must be greater than 0"
    
    if amount > 10_000_000:
        return False, "Amount must not exceed $10,000,000"
    
    # Check for more than 2 decimal places
    if round(amount, 2) != amount:
        return False, "Amount must have at most 2 decimal places"
    
    return True, None


def validate_payment_reason(reason: str) -> tuple[bool, Optional[str]]:
    """
    Validate payment reason.
    Returns (is_valid, error_message)
    """
    if not reason or not reason.strip():
        return False, "Payment reason is required"

    if len(reason) > 100:
        return False, "Payment reason must not exceed 100 characters"

    return True, None


# Made with Bob - Enterprise Payment Processing System