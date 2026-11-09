"""LAB5: konsument zdarzeń PaymentCompleted (producent: PAYMENT-SERVICE).

Kontrakt: exchange `pawoom.events` (topic), routing key `payment.completed`,
kolejka `scooter.payment-events` (durable). Właścicielem kolejki jest konsument.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db_models import ProcessedEventRow, ScooterPaymentStatsRow, ScooterRow
from app.models import PaymentSummary
from app.repository import ScooterNotFoundError

QUEUE_NAME = "scooter.payment-events"
ROUTING_KEY = "payment.completed"
EVENT_TYPE = "PaymentCompleted"


class InvalidEventError(ValueError):
    """Zdarzenie bez wymaganych pól albo z błędnymi typami (-> NACK, 422)."""


@dataclass(frozen=True)
class PaymentCompleted:
    event_id: str
    scooter_id: int
    payment_id: int
    amount: float
    occurred_at: str | None


def _positive_int(event: dict[str, Any], name: str) -> int:
    value = event.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidEventError(f"Field '{name}' must be a positive integer")
    return value


def parse_payment_completed(event: dict[str, Any]) -> PaymentCompleted | None:
    """Tolerant Reader: czyta tylko potrzebne pola, nieznane ignoruje.

    Zwraca None dla innego `event_type` (zdarzenie nas nie dotyczy - ACK bez skutku).
    """
    if not isinstance(event, dict):
        raise InvalidEventError("Event must be a JSON object")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 64:
        raise InvalidEventError("Field 'event_id' is required")
    event_type = event.get("event_type", EVENT_TYPE)
    if event_type != EVENT_TYPE:
        return None
    amount = event.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        raise InvalidEventError("Field 'amount' must be a positive number")
    occurred_at = event.get("occurred_at")
    return PaymentCompleted(
        event_id=event_id,
        scooter_id=_positive_int(event, "scooter_id"),
        payment_id=_positive_int(event, "payment_id"),
        amount=float(amount),
        occurred_at=occurred_at if isinstance(occurred_at, str) else None,
    )


class PaymentEventRepository:
    """Jedyne miejsce zapisu tabel `scooter_payment_stats` i `processed_events`."""

    def __init__(self, sessions: sessionmaker):
        self.sessions = sessions

    def summary(self, scooter_id: int) -> PaymentSummary:
        with self.sessions() as db:
            if db.get(ScooterRow, scooter_id) is None:
                raise ScooterNotFoundError(scooter_id)
            stats = db.get(ScooterPaymentStatsRow, scooter_id)
            if stats is None:
                return PaymentSummary(scooter_id=scooter_id)
            return PaymentSummary.model_validate(stats)

    def apply_payment_completed(self, event: PaymentCompleted) -> bool:
        """Jedna transakcja: sprawdzenie duplikatu -> zmiana stanu -> zapis event_id -> commit.

        Zwraca True, gdy zmiana została zastosowana, False dla duplikatu.
        """
        try:
            with self.sessions.begin() as db:
                if db.get(ProcessedEventRow, event.event_id) is not None:
                    return False  # duplikat: bez ponownej zmiany (wywołujący i tak wyśle ACK)
                if db.get(ScooterRow, event.scooter_id) is None:
                    raise ScooterNotFoundError(event.scooter_id)
                stats = db.get(ScooterPaymentStatsRow, event.scooter_id)
                if stats is None:
                    stats = ScooterPaymentStatsRow(
                        scooter_id=event.scooter_id, paid_payments_count=0, total_paid_amount=0.0
                    )
                    db.add(stats)
                stats.paid_payments_count += 1
                stats.total_paid_amount = round(stats.total_paid_amount + event.amount, 2)
                stats.last_payment_id = event.payment_id
                stats.last_paid_at = event.occurred_at
                db.add(
                    ProcessedEventRow(
                        event_id=event.event_id,
                        event_type=EVENT_TYPE,
                        processed_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
            return True  # commit nastąpił przy wyjściu z bloku begin()
        except IntegrityError:
            # Dwóch konsumentów jednocześnie z tym samym event_id: klucz główny
            # odrzucił drugi zapis, cała jego transakcja została wycofana.
            return False

    def processed_count(self) -> int:
        with self.sessions() as db:
            return db.scalar(select(func.count()).select_from(ProcessedEventRow))
