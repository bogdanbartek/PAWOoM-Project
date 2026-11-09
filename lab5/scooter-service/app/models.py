"""Modele Pydantic (kontrakt API) - bez zmian względem LAB1."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ScooterStatus = Literal["available", "rented", "maintenance"]
SCOOTER_STATUSES: tuple[str, ...] = ("available", "rented", "maintenance")


class ScooterCreate(BaseModel):
    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)


class Scooter(BaseModel):
    # from_attributes=True pozwala zbudować odpowiedź bezpośrednio z wiersza ORM.
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    model: str
    status: ScooterStatus = "available"


class PaymentSummary(BaseModel):
    """LAB5: podsumowanie płatności hulajnogi (aktualizowane zdarzeniami PaymentCompleted)."""

    model_config = ConfigDict(from_attributes=True)

    scooter_id: int
    paid_payments_count: int = 0
    total_paid_amount: float = 0.0
    last_payment_id: int | None = None
    last_paid_at: str | None = None
