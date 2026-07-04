import logging
from abc import ABC, abstractmethod
from typing import Optional

from typing_extensions import override

from sqlalchemy.orm import Session

from app.models import Payment

logger = logging.getLogger(__name__)


class PaymentProcessor(ABC):
    """
    Abstract base class for payment processors.
    Enables multi-rail support and extensibility.
    """
    
    def __init__(self, db: Session):
        self.db: Session = db
    
    @abstractmethod
    def process_payment(self, payment: Payment) -> bool:
        """
        Process a payment through this rail.
        Returns True if successful, False otherwise.
        """
        pass
    
    @abstractmethod
    def validate_payment(self, payment: Payment) -> tuple[bool, Optional[str]]:
        """
        Validate payment for this rail.
        Returns (is_valid, error_message)
        """
        pass
    
    @abstractmethod
    def get_rail_name(self) -> str:
        """Return the name of this payment rail."""
        pass


class ACHProcessor(PaymentProcessor):
    """
    ACH payment processor implementation.
    Handles ACH-specific validation and processing.
    """
    
    @override
    def get_rail_name(self) -> str:
        return "ACH"
    
    @override
    def validate_payment(self, payment: Payment) -> tuple[bool, Optional[str]]:
        """
        Validate ACH-specific requirements.
        """
        # ACH-specific validation
        if len(payment.routing_number) != 9:
            return False, "ACH requires 9-digit routing number"
        
        if len(payment.account_number) > 17:
            return False, "ACH account number cannot exceed 17 digits"
        
        if payment.amount > 1_000_000:
            return False, "ACH payment amount cannot exceed $1,000,000"
        
        return True, None
    
    @override
    def process_payment(self, payment: Payment) -> bool:
        """
        Process ACH payment.
        In a real system, this would interact with ACH network.
        """
        logger.info(f"Processing ACH payment {payment.id}")
        
        # Validate
        is_valid, error = self.validate_payment(payment)
        if not is_valid:
            logger.error(f"ACH validation failed for {payment.id}: {error}")
            return False
        
        # In real system: submit to ACH network
        logger.info(f"ACH payment {payment.id} submitted successfully")
        return True


class WireProcessor(PaymentProcessor):
    """
    Wire transfer processor implementation.
    Placeholder for wire transfer support.
    """
    
    @override
    def get_rail_name(self) -> str:
        return "WIRE"
    
    @override
    def validate_payment(self, payment: Payment) -> tuple[bool, Optional[str]]:
        """
        Validate wire-specific requirements.
        """
        if payment.amount < 1000:
            return False, "Wire transfers require minimum $1,000"
        
        return True, None
    
    @override
    def process_payment(self, payment: Payment) -> bool:
        """
        Process wire transfer.
        """
        logger.info(f"Processing wire transfer {payment.id}")
        
        is_valid, error = self.validate_payment(payment)
        if not is_valid:
            logger.error(f"Wire validation failed for {payment.id}: {error}")
            return False
        
        logger.info(f"Wire transfer {payment.id} submitted successfully")
        return True


class CheckProcessor(PaymentProcessor):
    """
    Check payment processor implementation.
    Placeholder for check processing support.
    """
    
    @override
    def get_rail_name(self) -> str:
        return "CHECK"
    
    @override
    def validate_payment(self, payment: Payment) -> tuple[bool, Optional[str]]:
        """
        Validate check-specific requirements.
        """
        # Check-specific validation
        return True, None
    
    @override
    def process_payment(self, payment: Payment) -> bool:
        """
        Process check payment.
        """
        logger.info(f"Processing check payment {payment.id}")
        return True


class PaymentProcessorFactory:
    """
    Factory for creating payment processors based on payment type.
    """
    
    @staticmethod
    def get_processor(db: Session, payment_type: str = "ACH") -> PaymentProcessor:
        """
        Get appropriate processor for payment type.
        """
        processors: dict[str, type[PaymentProcessor]] = {
            "ACH": ACHProcessor,
            "WIRE": WireProcessor,
            "CHECK": CheckProcessor,
        }
        
        processor_class = processors.get(payment_type.upper(), ACHProcessor)
        return processor_class(db)


# Made with Bob - Enterprise Payment Processing System