"""Modele ORM (SQLAlchemy) - osobno od modeli Pydantic w models.py."""
from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import SCOOTER_STATUSES

_ALLOWED = ", ".join(f"'{status}'" for status in SCOOTER_STATUSES)


class ScooterRow(Base):
    __tablename__ = "scooters"
    __table_args__ = (
        # Baza pilnuje, żeby w kolumnie nie znalazł się nieznany status.
        # Dozwolone PRZEJŚCIA między statusami pilnuje reguła w repozytorium.
        CheckConstraint(f"status IN ({_ALLOWED})", name="ck_scooters_status"),
        CheckConstraint("id > 0", name="ck_scooters_id_positive"),
    )

    # autoincrement=False: identyfikator nadaje klient (numer inwentarzowy), jak w LAB1.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
