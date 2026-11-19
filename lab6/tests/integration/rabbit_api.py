"""Pomocnik testów integracyjnych: stan kolejek i publikacja wiadomości przez API zarządzania RabbitMQ.

W LAB6 port AMQP (5672) nie jest opublikowany na hoście (`expose` w compose.yaml), więc testy
uruchamiane na hoście nie mogą łączyć się przez `pika`. Publikowany jest tylko panel Management
(127.0.0.1:15672, guest/guest), którego API HTTP wystarcza do obu potrzebnych operacji.
"""
import json
import os

import httpx

API_URL = os.getenv("RABBITMQ_API_URL", "http://127.0.0.1:15672")
AUTH = (os.getenv("RABBITMQ_USER", "guest"), os.getenv("RABBITMQ_PASSWORD", "guest"))
EXCHANGE = "pawoom.events"
ROUTING_KEY = "payment.completed"


def _client() -> httpx.Client:
    return httpx.Client(base_url=API_URL, auth=AUTH, timeout=10.0, trust_env=False)


def queue_depth(queue: str) -> int:
    """Liczba wiadomości czekających w kolejce, w czasie rzeczywistym.

    Statystyki z `GET /api/queues/...` odświeżają się co kilka sekund, więc test tuż po `pay` mógłby
    zobaczyć stan nieaktualny. Dlatego używamy operacji „get messages” z `ack_requeue_true`: pobiera
    jedną wiadomość i od razu zwraca ją do kolejki, a odpowiedź zawiera `message_count` (ile wiadomości
    zostało po pobranej).
    """
    with _client() as client:
        response = client.post(
            f"/api/queues/%2F/{queue}/get",
            json={"count": 1, "ackmode": "ack_requeue_true", "encoding": "auto"},
        )
        response.raise_for_status()
        messages = response.json()
        return 0 if not messages else 1 + messages[0]["message_count"]


def publish_raw(event: dict) -> None:
    """Publikacja z pominięciem producenta: symuluje ponowne dostarczenie tej samej wiadomości."""
    with _client() as client:
        response = client.post(
            f"/api/exchanges/%2F/{EXCHANGE}/publish",
            json={
                "properties": {"delivery_mode": 2, "content_type": "application/json"},
                "routing_key": ROUTING_KEY,
                "payload": json.dumps(event),
                "payload_encoding": "string",
            },
        )
        response.raise_for_status()
        assert response.json().get("routed") is True, "wiadomość nie trafiła do żadnej kolejki"
