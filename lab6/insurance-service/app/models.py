"""Modele Pydantic (kontrakt API) usługi ubezpieczeń."""
from typing import Literal

from pydantic import BaseModel, Field

InsuranceStatus = Literal["active", "cancelled"]


class InsuranceCreate(BaseModel):
    id: int = Field(gt=0)
    # Tylko odniesienie do hulajnogi - jej dane należą do Scooter Rental Service.
    scooter_id: int = Field(gt=0)
    # Stawka składki w procentach kwoty płatności (np. 5 = 5%); używana przy tworzeniu pokrycia.
    rate_percent: float = Field(gt=0, le=100, description="Składka w % kwoty płatności")


class Insurance(BaseModel):
    id: int
    scooter_id: int
    rate_percent: float
    status: InsuranceStatus = "active"


class InsuranceDetails(BaseModel):
    insurance: Insurance
    # Aktualne dane hulajnogi pobrane z SCOOTER-SERVICE w chwili żądania (nie kopia).
    scooter: dict


class CoverageRecord(BaseModel):
    """Rekord pokrycia ubezpieczeniowego tworzony automatycznie z zdarzenia PaymentCompleted.

    Powstaje tylko dla hulajnogi z aktywną polisą; `insurance_id` wskazuje tę polisę.
    """
    insurance_id: int
    scooter_id: int
    payment_id: int
    # Stawka polisy w chwili odbioru zdarzenia (kopia, żeby rekord był czytelny sam w sobie).
    rate_percent: float
    # Składka w PLN = kwota płatności × rate_percent / 100 — wyliczana automatycznie.
    premium: float
    payments_covered: int = 1
