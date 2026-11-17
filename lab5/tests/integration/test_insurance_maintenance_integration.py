"""LAB5: testy integracyjne usług INSURANCE-SERVICE i MAINTENANCE-SERVICE przez bramkę.

Wymagają działających: Redis, Eureka, RabbitMQ, wszystkich czterech usług i bramki
(najprościej: `.\\lab5\\scripts\\start-lab5.ps1`). Każdy test tworzy rekordy z unikalnym ID,
więc można je powtarzać bez czyszczenia bazy.

Uwaga na kolejki: jedno zdarzenie `payment.completed` trafia do DWÓCH kolejek
(`scooter.payment-events` i `insurance.payment-events`). Starsze testy (test_async_integration.py)
konsumują tylko kolejkę floty, więc kolejka ubezpieczeń może zawierać ich zaległe zdarzenia.
Dlatego każdy test zaczyna od opróżnienia obu kolejek, a kończy tak, żeby ich nie zostawiać.
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
SCOOTER_QUEUE = "scooter.payment-events"
INSURANCE_QUEUE = "insurance.payment-events"
CONSUME_SCOOTERS = "/api/scooters/payment-events/consume"
CONSUME_INSURANCES = "/api/insurances/payment-events/consume"


@pytest.fixture
def client():
    with httpx.Client(base_url=GATEWAY_URL, timeout=10.0, trust_env=False) as http:
        yield http


@pytest.fixture
def clean_queues(client):
    """Opróżnia obie kolejki przed testem (zaległości z innych testów) i po nim."""
    def drain():
        assert client.post(CONSUME_SCOOTERS).status_code == 200
        assert client.post(CONSUME_INSURANCES).status_code == 200

    drain()
    yield
    drain()


def unique_id() -> int:
    return uuid.uuid4().int % 900_000_000 + 100_000_000


def queue_depth(queue: str) -> int:
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    try:
        return connection.channel().queue_declare(queue=queue, durable=True, passive=True).method.message_count
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


def create_scooter(client) -> int:
    scooter_id = unique_id()
    response = client.post(
        "/api/scooters",
        json={"id": scooter_id, "name": f"IT-{scooter_id}", "model": "Integration Test"},
    )
    assert response.status_code == 201, response.text
    return scooter_id


def coverage_for(client, payment_id: int) -> list[dict]:
    response = client.get("/api/coverage")
    assert response.status_code == 200
    return [record for record in response.json() if record["payment_id"] == payment_id]


# --- Insurance Service: przepływ synchroniczny (Insurance -> Scooter przez Eurekę) ----------


def test_insurance_created_and_details_read_scooter_through_eureka(client):
    scooter_id = create_scooter(client)
    insurance_id = unique_id()

    created = client.post(
        "/api/insurances", json={"id": insurance_id, "scooter_id": scooter_id, "premium": 49.99}
    )
    details = client.get(f"/api/insurances/{insurance_id}/details")

    assert created.status_code == 201, created.text
    assert created.headers["x-gateway"] == "lab4"
    assert created.json() == {
        "id": insurance_id, "scooter_id": scooter_id, "premium": 49.99, "status": "active"
    }
    assert details.status_code == 200
    body = details.json()
    assert body["insurance"]["id"] == insurance_id
    # Dane hulajnogi pochodzą z SCOOTER-SERVICE (nie są kopią w usłudze ubezpieczeń).
    assert body["scooter"]["id"] == scooter_id
    assert body["scooter"]["name"] == f"IT-{scooter_id}"


def test_insurance_for_missing_scooter_returns_404_and_stores_nothing(client):
    insurance_id = unique_id()

    response = client.post(
        "/api/insurances", json={"id": insurance_id, "scooter_id": unique_id(), "premium": 10}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Scooter not found"}
    assert response.headers["x-gateway"] == "lab4"
    assert client.get(f"/api/insurances/{insurance_id}").status_code == 404


def test_insurance_cancel_rule_and_validation(client):
    scooter_id = create_scooter(client)
    insurance_id = unique_id()
    assert client.post(
        "/api/insurances", json={"id": insurance_id, "scooter_id": scooter_id, "premium": 20}
    ).status_code == 201

    cancelled = client.post(f"/api/insurances/{insurance_id}/cancel")
    again = client.post(f"/api/insurances/{insurance_id}/cancel")
    duplicate = client.post(
        "/api/insurances", json={"id": insurance_id, "scooter_id": scooter_id, "premium": 20}
    )
    invalid = client.post("/api/insurances", json={"id": unique_id(), "scooter_id": scooter_id, "premium": -5})

    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert again.status_code == 409
    assert again.json() == {"detail": "Insurance is already cancelled"}
    assert duplicate.status_code == 409
    assert invalid.status_code == 422
    assert client.get(f"/api/insurances/{insurance_id}").json()["status"] == "cancelled"


# --- Maintenance Service: maszyna stanów + przepływ synchroniczny ---------------------------


def test_job_state_machine_through_gateway(client):
    scooter_id = create_scooter(client)
    job_id = unique_id()
    created = client.post(
        "/api/jobs", json={"id": job_id, "scooter_id": scooter_id, "description": "Wymiana hamulca"}
    )
    assert created.status_code == 201, created.text
    assert created.headers["x-gateway"] == "lab4"
    assert created.json()["status"] == "pending"

    # Niedozwolone: zakończenie zlecenia, które nie zostało rozpoczęte.
    early = client.post(f"/api/jobs/{job_id}/complete")
    assert early.status_code == 409
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "pending"  # stan bez zmian

    started = client.post(f"/api/jobs/{job_id}/start")
    started_again = client.post(f"/api/jobs/{job_id}/start")
    completed = client.post(f"/api/jobs/{job_id}/complete")
    completed_again = client.post(f"/api/jobs/{job_id}/complete")
    details = client.get(f"/api/jobs/{job_id}/details")

    assert started.status_code == 200 and started.json()["status"] == "in_progress"
    assert started_again.status_code == 409
    assert completed.status_code == 200 and completed.json()["status"] == "completed"
    assert completed_again.status_code == 409
    assert details.status_code == 200
    assert details.json()["job"]["status"] == "completed"
    assert details.json()["scooter"]["id"] == scooter_id  # aktualne dane z SCOOTER-SERVICE


def test_job_for_missing_scooter_returns_404_and_missing_job_404(client):
    job_id = unique_id()

    missing_scooter = client.post(
        "/api/jobs", json={"id": job_id, "scooter_id": unique_id(), "description": "x"}
    )

    assert missing_scooter.status_code == 404
    assert missing_scooter.json() == {"detail": "Scooter not found"}
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.get(f"/api/jobs/{unique_id()}").status_code == 404
    assert client.post("/api/jobs", json={"id": 0, "scooter_id": 1, "description": ""}).status_code == 422


# --- Zdarzenia: jedno pay -> dwie kolejki (fan-out) ------------------------------------------


def test_pay_fans_out_to_both_queues_and_each_consumer_applies_it(client, clean_queues):
    scooter_id = create_scooter(client)
    payment_id = unique_id()
    assert client.post(
        "/api/payments", json={"id": payment_id, "scooter_id": scooter_id, "amount": 200.0}
    ).status_code == 201
    assert queue_depth(SCOOTER_QUEUE) == 0 and queue_depth(INSURANCE_QUEUE) == 0  # create nie publikuje

    paid = client.post(f"/api/payments/{payment_id}/pay")

    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    # Producent nie zna konsumentów: jedna publikacja, dwie kolejki związane tym samym kluczem.
    assert queue_depth(SCOOTER_QUEUE) == 1
    assert queue_depth(INSURANCE_QUEUE) == 1
    assert coverage_for(client, payment_id) == []  # przed odbiorem brak pokrycia (spójność ostateczna)

    fleet = client.post(CONSUME_SCOOTERS).json()
    assert queue_depth(SCOOTER_QUEUE) == 0
    assert queue_depth(INSURANCE_QUEUE) == 1  # odbiór przez flotę nie zabiera wiadomości ubezpieczeniom
    insurance = client.post(CONSUME_INSURANCES).json()

    assert (fleet["consumed_messages"], fleet["applied_events"]) == (1, 1)
    assert (insurance["consumed_messages"], insurance["applied_events"]) == (1, 1)
    summary = client.get(f"/api/scooters/{scooter_id}/payment-summary").json()
    assert summary["paid_payments_count"] == 1 and summary["total_paid_amount"] == 200.0
    records = coverage_for(client, payment_id)
    assert len(records) == 1
    assert records[0]["scooter_id"] == scooter_id
    assert records[0]["premium"] == 10.0  # 5% z 200.0
    assert queue_depth(SCOOTER_QUEUE) == 0 and queue_depth(INSURANCE_QUEUE) == 0


def test_insurance_consumer_is_idempotent(client, clean_queues):
    scooter_id = create_scooter(client)  # istniejąca hulajnoga, bo zdarzenie trafi też do kolejki floty
    payment_id = unique_id()
    event = {
        "event_id": f"evt-it-{uuid.uuid4().hex[:12]}",
        "event_type": "PaymentCompleted",
        "payment_id": payment_id,
        "scooter_id": scooter_id,
        "amount": 80.0,
        "occurred_at": "2026-11-17T12:00:00+00:00",
    }
    publish_raw(event)
    publish_raw(event)  # to samo zdarzenie dostarczone drugi raz

    result = client.post(CONSUME_INSURANCES).json()
    client.post(CONSUME_SCOOTERS)  # to samo zdarzenie czeka też w kolejce floty

    assert result["consumed_messages"] == 2
    assert (result["applied_events"], result["duplicate_events"]) == (1, 1)
    records = coverage_for(client, payment_id)
    assert len(records) == 1
    assert records[0]["premium"] == 4.0  # 5% z 80.0, naliczone raz


def test_rejected_pay_publishes_to_neither_queue(client, clean_queues):
    scooter_id = create_scooter(client)
    payment_id = unique_id()
    assert client.post(
        "/api/payments", json={"id": payment_id, "scooter_id": scooter_id, "amount": 30}
    ).status_code == 201
    assert client.post(f"/api/payments/{payment_id}/pay").status_code == 200
    client.post(CONSUME_SCOOTERS)
    client.post(CONSUME_INSURANCES)

    conflict = client.post(f"/api/payments/{payment_id}/pay")
    missing = client.post(f"/api/payments/{unique_id()}/pay")

    assert conflict.status_code == 409
    assert missing.status_code == 404
    assert queue_depth(SCOOTER_QUEUE) == 0
    assert queue_depth(INSURANCE_QUEUE) == 0
