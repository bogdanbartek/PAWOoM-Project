"""LAB5: testy integracyjne przepływu asynchronicznego przez bramkę i prawdziwy RabbitMQ.

Wymagają działających: Redis, Eureka, RabbitMQ (`docker compose up -d`), obu usług i bramki.
Każdy test tworzy własne rekordy z unikalnym ID, więc można je powtarzać bez czyszczenia bazy.
"""
import json
import os
import uuid

import httpx
import pika
import pytest

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8080")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@127.0.0.1:5672/%2F")
EXCHANGE = "pawoom.events"
ROUTING_KEY = "payment.completed"
QUEUE = "scooter.payment-events"
CONSUME = "/api/scooters/payment-events/consume"


@pytest.fixture
def client():
    with httpx.Client(base_url=GATEWAY_URL, timeout=10.0, trust_env=False) as http:
        yield http


def unique_id() -> int:
    return uuid.uuid4().int % 900_000_000 + 100_000_000


def queue_ready() -> int:
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    try:
        return connection.channel().queue_declare(queue=QUEUE, durable=True, passive=True).method.message_count
    finally:
        connection.close()


def publish_raw(event: dict) -> None:
    """Publikacja z pominięciem producenta - symuluje ponowne dostarczenie tej samej wiadomości."""
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    try:
        connection.channel().basic_publish(
            exchange=EXCHANGE,
            routing_key=ROUTING_KEY,
            body=json.dumps(event).encode(),
            properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
        )
    finally:
        connection.close()


def scooter_with_payment(client, amount=9.5):
    scooter_id, payment_id = unique_id(), unique_id()
    assert client.post(
        "/api/scooters", json={"id": scooter_id, "name": f"IT-{scooter_id}", "model": "Integration Test"}
    ).status_code == 201
    assert client.post(
        "/api/payments", json={"id": payment_id, "scooter_id": scooter_id, "amount": amount}
    ).status_code == 201
    return scooter_id, payment_id


def test_pay_publishes_event_consumer_updates_state_and_cache(client):
    client.post(CONSUME)  # opróżnia kolejkę z resztek wcześniejszych prób
    scooter_id, payment_id = scooter_with_payment(client)
    first = client.get(f"/api/scooters/{scooter_id}/payment-summary")
    second = client.get(f"/api/scooters/{scooter_id}/payment-summary")
    assert (first.headers["x-cache"], second.headers["x-cache"]) == ("MISS", "HIT")
    assert second.json()["paid_payments_count"] == 0

    paid = client.post(f"/api/payments/{payment_id}/pay")
    assert paid.status_code == 200
    assert paid.headers["x-gateway"] == "lab4"
    assert queue_ready() == 1  # trwała wiadomość czeka na konsumenta

    consumed = client.post(CONSUME)
    after = client.get(f"/api/scooters/{scooter_id}/payment-summary")
    again = client.get(f"/api/scooters/{scooter_id}/payment-summary")

    assert consumed.status_code == 200
    assert consumed.json()["consumed_messages"] == 1
    assert consumed.json()["applied_events"] == 1
    assert queue_ready() == 0  # ACK po zapisie
    assert after.headers["x-cache"] == "MISS"  # konsument unieważnił klucz po commicie
    assert after.json()["paid_payments_count"] == 1
    assert after.json()["total_paid_amount"] == 9.5
    assert after.json()["last_payment_id"] == payment_id
    assert again.headers["x-cache"] == "HIT"


def test_duplicate_delivery_is_applied_once(client):
    client.post(CONSUME)
    scooter_id, _ = scooter_with_payment(client)
    event = {
        "event_id": f"evt-it-{uuid.uuid4().hex[:12]}",
        "event_type": "PaymentCompleted",
        "payment_id": unique_id(),
        "scooter_id": scooter_id,
        "amount": 4.0,
        "occurred_at": "2026-11-09T12:00:00+00:00",
    }
    publish_raw(event)
    publish_raw(event)

    result = client.post(CONSUME).json()
    summary = client.get(f"/api/scooters/{scooter_id}/payment-summary").json()

    assert result["consumed_messages"] == 2
    assert (result["applied_events"], result["duplicate_events"]) == (1, 1)
    assert summary["paid_payments_count"] == 1
    assert summary["total_paid_amount"] == 4.0


def test_rejected_operations_do_not_publish(client):
    client.post(CONSUME)
    _, payment_id = scooter_with_payment(client)
    assert client.post(f"/api/payments/{payment_id}/pay").status_code == 200
    client.post(CONSUME)

    conflict = client.post(f"/api/payments/{payment_id}/pay")
    missing = client.post(f"/api/payments/{unique_id()}/pay")
    invalid = client.post("/api/payments", json={"id": unique_id(), "scooter_id": 1, "amount": -1})

    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "Payment is already paid"}
    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert queue_ready() == 0
