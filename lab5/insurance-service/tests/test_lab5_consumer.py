"""LAB5: Insurance Service jako konsument zdarzeń PaymentCompleted."""
import pytest
from fastapi.testclient import TestClient

from app.events import QUEUE_NAME, ROUTING_KEY
from app.main import create_app
from app.messaging import InMemoryEventBroker
from tests.conftest import FakeEurekaClient


def make_event(event_id="evt-001", scooter_id=1, payment_id=1, amount=100.0):
    return {
        "event_id": event_id,
        "event_type": "PaymentCompleted",
        "payment_id": payment_id,
        "scooter_id": scooter_id,
        "amount": amount,
        "occurred_at": "2026-11-17T10:00:00+00:00",
    }


@pytest.fixture
def broker_with_event(broker):
    broker.bind_queue(QUEUE_NAME, ROUTING_KEY)
    broker.publish(ROUTING_KEY, make_event())
    return broker


def test_consume_creates_coverage_record(client, broker_with_event):
    response = client.post("/insurances/payment-events/consume")

    assert response.status_code == 200
    data = response.json()
    assert data["consumed_messages"] == 1
    assert data["applied_events"] == 1
    assert data["total_coverage_records"] == 1

    coverage = client.get("/coverage").json()
    assert len(coverage) == 1
    assert coverage[0]["scooter_id"] == 1
    assert coverage[0]["payment_id"] == 1
    assert coverage[0]["premium"] == 5.0  # 5% z 100.0


def test_consume_is_idempotent_for_same_event(client, broker):
    broker.bind_queue(QUEUE_NAME, ROUTING_KEY)
    event = make_event()
    broker.publish(ROUTING_KEY, event)
    broker.publish(ROUTING_KEY, event)  # duplikat tego samego event_id

    response = client.post("/insurances/payment-events/consume")

    assert response.status_code == 200
    data = response.json()
    assert data["consumed_messages"] == 2
    assert data["applied_events"] == 1
    assert data["duplicate_events"] == 1
    assert data["total_coverage_records"] == 1


def test_consume_ignores_other_event_types(client, broker):
    broker.bind_queue(QUEUE_NAME, ROUTING_KEY)
    other_event = {**make_event(), "event_type": "SomeOtherEvent"}
    broker.publish(ROUTING_KEY, other_event)

    response = client.post("/insurances/payment-events/consume")

    assert response.status_code == 200
    assert response.json()["ignored_events"] == 1
    assert response.json()["total_coverage_records"] == 0


def test_consume_returns_503_when_broker_unavailable(client):
    down_broker = InMemoryEventBroker(down=True)
    with TestClient(create_app(eureka_client=FakeEurekaClient(), event_broker=down_broker)) as c:
        response = c.post("/insurances/payment-events/consume")
    assert response.status_code == 503
    assert response.json() == {"detail": "RabbitMQ broker is unavailable"}


def test_consume_multiple_events_for_same_scooter(client, broker):
    broker.bind_queue(QUEUE_NAME, ROUTING_KEY)
    broker.publish(ROUTING_KEY, make_event(event_id="evt-001", payment_id=1, amount=100.0))
    broker.publish(ROUTING_KEY, make_event(event_id="evt-002", payment_id=2, amount=200.0))

    response = client.post("/insurances/payment-events/consume")

    assert response.status_code == 200
    assert response.json()["applied_events"] == 2
    assert response.json()["total_coverage_records"] == 2

    coverage = client.get("/coverage").json()
    premiums = {r["payment_id"]: r["premium"] for r in coverage}
    assert premiums[1] == 5.0   # 5% z 100
    assert premiums[2] == 10.0  # 5% z 200


def test_empty_queue_returns_zero_consumed(client, broker):
    broker.bind_queue(QUEUE_NAME, ROUTING_KEY)

    response = client.post("/insurances/payment-events/consume")

    assert response.status_code == 200
    assert response.json()["consumed_messages"] == 0
    assert response.json()["total_coverage_records"] == 0
