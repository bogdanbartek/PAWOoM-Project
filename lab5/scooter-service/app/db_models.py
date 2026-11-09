"""Modele ORM (SQLAlchemy) - osobno od modeli Pydantic w models.py."""
from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
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


# --- LAB5: skutek zdarzenia PaymentCompleted i idempotentność konsumenta -------------


class ScooterPaymentStatsRow(Base):
    """Podsumowanie opłaconych płatności hulajnogi - stan aktualizowany przez konsumenta."""

    __tablename__ = "scooter_payment_stats"
    __table_args__ = (
        CheckConstraint("paid_payments_count >= 0", name="ck_stats_count_non_negative"),
        CheckConstraint("total_paid_amount >= 0", name="ck_stats_amount_non_negative"),
    )

    scooter_id: Mapped[int] = mapped_column(Integer, ForeignKey("scooters.id"), primary_key=True)
    paid_payments_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_paid_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_payment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_paid_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ProcessedEventRow(Base):
    """Identyfikatory przetworzonych zdarzeń. Klucz główny = event_id, więc duplikat nie przejdzie."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    processed_at: Mapped[str] = mapped_column(String(40), nullable=False)
