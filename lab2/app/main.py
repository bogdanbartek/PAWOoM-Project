from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field


ScooterStatus = Literal["available", "rented", "maintenance"]


class ScooterCreate(BaseModel):
    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)


class Scooter(BaseModel):
    id: int
    name: str
    model: str
    status: ScooterStatus = "available"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Scooter Rental Service",
        description="Student microservice for scooter rentals",
        version="0.1.0",
    )

    # Każda instancja aplikacji ma własny magazyn w pamięci.
    # Zastąp "items" nazwą wynikającą z twojej domeny.
    app.state.scooters = {}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "Scooter Rental Service"}

    @app.get("/scooters", response_model=list[Scooter])
    def list_scooters(request: Request) -> list[Scooter]:
        return list(request.app.state.scooters.values())

    @app.get("/scooters/{scooter_id}", response_model=Scooter)
    def get_scooter(scooter_id: int, request: Request) -> Scooter:
        scooter = request.app.state.scooters.get(scooter_id)

        if scooter is None:
            raise HTTPException(status_code=404, detail="Scooter not found")

        return scooter

    @app.post("/scooters", response_model=Scooter, status_code=201)
    def create_scooter(data: ScooterCreate, request: Request) -> Scooter:
        scooters = request.app.state.scooters

        if data.id in scooters:
            raise HTTPException(
                status_code=409,
                detail="Scooter with this ID already exists",
            )

        scooter = Scooter(**data.model_dump())
        scooters[scooter.id] = scooter

        return scooter

    @app.post("/scooters/{scooter_id}/rent", response_model=Scooter)
    def rent_scooter(scooter_id: int, request: Request) -> Scooter:
        scooters = request.app.state.scooters
        scooter = scooters.get(scooter_id)

        if scooter is None:
            raise HTTPException(status_code=404, detail="Scooter not found")

        # Reguła biznesowa: można wypożyczyć tylko dostępny skuter.
        if scooter.status != "available":
            raise HTTPException(
                status_code=409,
                detail="Scooter is not available for rental",
            )

        updated = scooter.model_copy(update={"status": "rented"})
        scooters[scooter_id] = updated

        return updated

    @app.post("/scooters/{scooter_id}/return", response_model=Scooter)
    def return_scooter(scooter_id: int, request: Request) -> Scooter:
        scooters = request.app.state.scooters
        scooter = scooters.get(scooter_id)

        if scooter is None:
            raise HTTPException(status_code=404, detail="Scooter not found")

        # Nie można zwrócić skutera, który nie jest wypożyczony.
        if scooter.status != "rented":
            raise HTTPException(
                status_code=409,
                detail="Scooter is not currently rented",
            )

        updated = scooter.model_copy(update={"status": "available"})
        scooters[scooter_id] = updated

        return updated

    # TODO: dodaj tutaj modele/endpointy własnej domeny lub dołącz routery.
    # Magazyn twórz tylko raz na aplikację; endpointy korzystają z app.state.
    return app


app = create_app()


# TODO:
# 1. Choose your domain and name the service.
# 2. Add your domain models.
# 3. Add one list endpoint and one detail endpoint.
# 4. Add one create or update endpoint.
# 5. Add a business rule beyond types, required fields and unique identifiers.
# 6. Reject invalid operations before changing state; handle 404, 409 and 422.
# 7. Add at least three domain tests with fresh application state for each test.
# 8. Verify write/read and restart via HTTP; complete the README.