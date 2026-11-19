"""Repozytorium hulajnóg: jedyne miejsce, które czyta i zapisuje tabelę `scooters`.

Każda operacja otwiera własną sesję i zamyka ją po zakończeniu.
Kolejność w operacjach zapisu: odczyt stanu -> sprawdzenie reguły -> zmiana -> commit.
Wyjątek rzucony wewnątrz `sessions.begin()` powoduje rollback, więc odrzucona
operacja nie zostawia częściowo zmienionych danych.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db_models import ScooterRow
from app.models import Scooter, ScooterCreate


class ScooterNotFoundError(LookupError):
    """Hulajnoga o podanym id nie istnieje (-> 404)."""


class DuplicateScooterError(ValueError):
    """Hulajnoga o podanym id już istnieje (-> 409)."""


class ScooterStateError(ValueError):
    """Naruszenie reguły biznesowej: niedozwolone przejście statusu (-> 409)."""


class ScooterRepository:
    def __init__(self, sessions: sessionmaker):
        self.sessions = sessions

    def list_all(self) -> list[Scooter]:
        with self.sessions() as db:
            rows = db.scalars(select(ScooterRow).order_by(ScooterRow.id)).all()
            return [Scooter.model_validate(row) for row in rows]

    def get(self, scooter_id: int) -> Scooter:
        with self.sessions() as db:
            row = db.get(ScooterRow, scooter_id)
            if row is None:
                raise ScooterNotFoundError(scooter_id)
            return Scooter.model_validate(row)

    def create(self, data: ScooterCreate) -> Scooter:
        try:
            with self.sessions.begin() as db:
                if db.get(ScooterRow, data.id) is not None:
                    raise DuplicateScooterError("Scooter with this ID already exists")
                row = ScooterRow(**data.model_dump(), status="available")
                db.add(row)
                db.flush()
                return Scooter.model_validate(row)
        except IntegrityError as exc:
            # Gdy dwa żądania jednocześnie przejdą sprawdzenie powyżej, unikalność
            # klucza głównego w bazie i tak odrzuci drugie - mapujemy to na 409.
            # Mapujemy tylko IntegrityError; inne błędy bazy nie stają się 409.
            raise DuplicateScooterError("Scooter with this ID already exists") from exc

    def rent(self, scooter_id: int) -> Scooter:
        return self._change_status(
            scooter_id,
            required="available",
            new="rented",
            error="Scooter is not available for rental",
        )

    def return_scooter(self, scooter_id: int) -> Scooter:
        return self._change_status(
            scooter_id,
            required="rented",
            new="available",
            error="Scooter is not currently rented",
        )

    def _change_status(self, scooter_id: int, required: str, new: str, error: str) -> Scooter:
        with self.sessions.begin() as db:
            row = db.get(ScooterRow, scooter_id)  # 1. odczyt stanu
            if row is None:
                raise ScooterNotFoundError(scooter_id)
            if row.status != required:  # 2. reguła biznesowa z LAB1
                raise ScooterStateError(error)
            row.status = new  # 3. zmiana
            result = Scooter.model_validate(row)
        return result  # 4. commit nastąpił przy wyjściu z bloku begin()
