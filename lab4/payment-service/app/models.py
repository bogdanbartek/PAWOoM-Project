"""Modele Pydantic (kontrakt API) usługi płatności."""
from typing import Literal

from pydantic import BaseModel, Field

PaymentStatus = Literal["pending", "paid"]


class PaymentCreate(BaseModel):
    id: int = Field(gt=0)
    # Tylko odniesienie do hulajnogi - jej dane należą do Scooter Rental Service.
    scooter_id: int = Field(gt=0)
    amount: float = Field(gt=0, le=10_000)


class Payment(BaseModel):
    id: int
    scooter_id: int
    amount: float
    status: PaymentStatus = "pending"


class PaymentDetails(BaseModel):
    payment: Payment
    # Aktualne dane hulajnogi pobrane z SCOOTER-SERVICE w chwili żądania (nie kopia).
    scooter: dict
