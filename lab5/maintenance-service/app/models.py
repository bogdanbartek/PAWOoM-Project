"""Modele Pydantic (kontrakt API) usługi serwisowej."""
from typing import Literal

from pydantic import BaseModel, Field

MaintenanceStatus = Literal["pending", "in_progress", "completed"]


class MaintenanceCreate(BaseModel):
    id: int = Field(gt=0)
    # Tylko odniesienie do hulajnogi - jej dane należą do Scooter Rental Service.
    scooter_id: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=500)


class MaintenanceJob(BaseModel):
    id: int
    scooter_id: int
    description: str
    status: MaintenanceStatus = "pending"


class MaintenanceDetails(BaseModel):
    job: MaintenanceJob
    # Aktualne dane hulajnogi pobrane z SCOOTER-SERVICE w chwili żądania (nie kopia).
    scooter: dict
