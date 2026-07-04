# pyright: reportAttributeAccessIssue=false, reportUnknownVariableType=false, reportUntypedFunctionDecorator=false, reportCallIssue=false, reportUnannotatedClassAttribute=false

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PaymentCreate(BaseModel):
    amount: float = Field(..., gt=0, le=10000000)
    routing_number: str = Field(..., min_length=9, max_length=9)
    account_number: str = Field(..., min_length=4, max_length=17)
    payment_reason: str = Field(..., min_length=1, max_length=100)
    idempotency_key: str = Field(..., min_length=1, max_length=100)

    @field_validator("routing_number")
    @classmethod
    def validate_routing_number(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("routing_number must contain only digits")
        return value

    @field_validator("account_number")
    @classmethod
    def validate_account_number(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("account_number must contain only digits")
        return value


class PaymentResponse(BaseModel):
    transaction_id: str
    status: str
    amount: float
    routing_number: str
    account_number: str
    payment_reason: str
    batch_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def ensure_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    model_config = ConfigDict(from_attributes=True)


class PaymentListResponse(BaseModel):
    payments: list[PaymentResponse]

# Made with Bob
