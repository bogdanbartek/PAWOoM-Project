"""Modele Pydantic (kontrakt API) usługi ubezpieczeń."""
from typing import Literal

from pydantic import BaseModel, Field

InsuranceStatus = Literal["active", "cancelled"]


class InsuranceCreate(BaseModel):
    id: int = Field(gt=0)
    # Tylko odniesienie do hulajnogi - jej dane należą do Scooter Rental Service.
    scooter_id: int = Field(gt=0)
    premium: float = Field(gt=0, le=5_000, description="Składka ubezpieczeniowa (PLN)")


class Insurance(BaseModel):
    id: int
    scooter_id: int
    premium: float
    status: InsuranceStatus = "active"


class InsuranceDetails(BaseModel):
    insurance: Insurance
    # Aktualne dane hulajnogi pobrane z SCOOTER-SERVICE w chwili żądania (nie kopia).
    scooter: dict


class CoverageRecord(BaseModel):
    """Rekord pokrycia ubezpieczeniowego tworzony automatycznie z zdarzenia PaymentCompleted."""
    scooter_id: int
    payment_id: int
    # Składka = 5% wartości płatności — wyliczana automatycznie.
    premium: float
    payments_covered: int = 1
