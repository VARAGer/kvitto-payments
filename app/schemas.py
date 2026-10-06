from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

MAX_ID = 2**63 - 1


class PaymentMethod(str, Enum):
    card = "card"
    sbp = "sbp"
    installment = "installment"


class PaymentStatus(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"


class TariffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    price: int


class PaymentCreate(BaseModel):
    tariff_id: int = Field(gt=0, le=MAX_ID)
    email: EmailStr
    method: PaymentMethod
    installment_months: Literal[3, 6, 12] | None = None
    promo_code: str | None = None

    @field_validator("promo_code")
    @classmethod
    def validate_promo_code(cls, value: str | None) -> str | None:
        if value is not None and value.upper() != "KVITTO10":
            raise ValueError("unknown promo code")
        return value

    @model_validator(mode="after")
    def validate_installment_months(self):
        if self.method == PaymentMethod.installment and self.installment_months is None:
            raise ValueError("installment_months is required for installment")
        if self.method != PaymentMethod.installment and self.installment_months is not None:
            raise ValueError("installment_months is only allowed for installment")
        return self


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: PaymentStatus
    tariff_id: int
    amount: int
    discount: int
    method: PaymentMethod
    installment_months: int | None
    schedule: list[int] | None
    email: EmailStr
    created_at: datetime


class BankWebhook(BaseModel):
    payment_id: int = Field(gt=0, le=MAX_ID)
    status: PaymentStatus


class HealthOut(BaseModel):
    status: Literal["ok"]
