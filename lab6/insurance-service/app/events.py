"""LAB5: konsument zdarzeń PaymentCompleted (insurance-service).

Kontrakt: exchange `pawoom.events` (topic), routing key `payment.completed`,
kolejka `insurance.payment-events` (durable). Właścicielem kolejki jest konsument.

Gdy płatność zostanie opłacona, insurance-service automatycznie tworzy
rekord pokrycia ubezpieczeniowego (składka = 5% wartości płatności).
"""
from dataclasses import dataclass
from typing import Any

QUEUE_NAME = "insurance.payment-events"
ROUTING_KEY = "payment.completed"
EVENT_TYPE = "PaymentCompleted"
PREMIUM_RATE = 0.05  # 5% wartości płatności jako składka


class InvalidEventError(ValueError):
    """Zdarzenie bez wymaganych pól albo z błędnymi typami (-> NACK, 422)."""


@dataclass(frozen=True)
class PaymentCompleted:
    event_id: str
    scooter_id: int
    payment_id: int
    amount: float


def parse_payment_completed(event: dict[str, Any]) -> PaymentCompleted | None:
    """Tolerant Reader: czyta tylko potrzebne pola, nieznane ignoruje.

    Zwraca None dla innego `event_type` (zdarzenie nas nie dotyczy - ACK bez skutku).
    """
    if not isinstance(event, dict):
        raise InvalidEventError("Event must be a JSON object")
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise InvalidEventError("Field 'event_id' is required")
    event_type = event.get("event_type", EVENT_TYPE)
    if event_type != EVENT_TYPE:
        return None
    scooter_id = event.get("scooter_id")
    if isinstance(scooter_id, bool) or not isinstance(scooter_id, int) or scooter_id <= 0:
        raise InvalidEventError("Field 'scooter_id' must be a positive integer")
    payment_id = event.get("payment_id")
    if isinstance(payment_id, bool) or not isinstance(payment_id, int) or payment_id <= 0:
        raise InvalidEventError("Field 'payment_id' must be a positive integer")
    amount = event.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        raise InvalidEventError("Field 'amount' must be a positive number")
    return PaymentCompleted(
        event_id=event_id,
        scooter_id=scooter_id,
        payment_id=payment_id,
        amount=float(amount),
    )
