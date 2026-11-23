"""LAB5: Insurance Service jako konsument zdarzeń PaymentCompleted."""
import pytest
from fastapi.testclient import TestClient

from app.events import QUEUE_NAME, ROUTING_KEY
from app.main import create_app
from app.messaging import InMemoryEventBroker
from tests.conftest import FakeEurekaClient, insurance_body


def make_event(event_id="evt-001", scooter_id=1, payment_id=1, amount=100.0):
    return {
        "event_id": event_id,
        "event_type": "PaymentCompleted",
        "payment_id": payment_id,
        "scooter_id": scooter_id,
        "amount": amount,
        "occurred_at": "2026-11-17T10:00:00+00:00",
    }


def create_policy(client, insurance_id=1, scooter_id=1, rate_percent=5.0):
    response = client.post("/insurances", json=insurance_body(insurance_id, scooter_id, rate_percent))
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def broker_with_event(broker):
    broker.bind_queue(QUEUE_NAME, ROUTING_KEY)
    broker.publish(ROUTING_KEY, make_event())
    return broker


def test_consume_creates_coverage_record(client, broker_with_event):
    create_policy(client)

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
    assert coverage[0]["rate_percent"] == 5.0
    assert coverage[0]["insurance_id"] == 1  # rekord wskazuje polisę hulajnogi


def test_consume_is_idempotent_for_same_event(client, broker):
    create_policy(client)
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
    create_policy(client)
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


def test_payment_without_policy_creates_no_coverage(client, broker_with_event):
    response = client.post("/insurances/payment-events/consume")

    assert response.status_code == 200
    data = response.json()
    assert data["consumed_messages"] == 1  # wiadomość odebrana i potwierdzona (ACK)
    assert data["applied_events"] == 0
    assert data["uninsured_events"] == 1
    assert data["total_coverage_records"] == 0
    assert client.get("/coverage").json() == []


def test_cancelled_policy_does_not_cover_payment(client, broker_with_event):
    create_policy(client)
    assert client.post("/insurances/1/cancel").status_code == 200

    data = client.post("/insurances/payment-events/consume").json()

    assert data["uninsured_events"] == 1
    assert data["total_coverage_records"] == 0


def test_uninsured_event_redelivered_counts_as_duplicate(client, broker):
    broker.bind_queue(QUEUE_NAME, ROUTING_KEY)
    broker.publish(ROUTING_KEY, make_event())
    client.post("/insurances/payment-events/consume")
    create_policy(client)  # polisa dodana dopiero po przetworzeniu zdarzenia
    broker.publish(ROUTING_KEY, make_event())  # to samo event_id dostarczone ponownie

    data = client.post("/insurances/payment-events/consume").json()

    assert data["duplicate_events"] == 1  # zdarzenie już przetworzone, pokrycie nie powstaje wstecz
    assert data["total_coverage_records"] == 0


def test_premium_uses_rate_from_policy(client, broker):
    create_policy(client, rate_percent=12.5)
    broker.bind_queue(QUEUE_NAME, ROUTING_KEY)
    broker.publish(ROUTING_KEY, make_event(amount=80.0))

    client.post("/insurances/payment-events/consume")

    record = client.get("/coverage").json()[0]
    assert record["rate_percent"] == 12.5
    assert record["premium"] == 10.0  # 12,5% z 80.0


@pytest.mark.parametrize("rate", [0, -5, 100.5])
def test_rate_percent_out_of_range_is_rejected(client, eureka_fake, rate):
    response = client.post("/insurances", json=insurance_body(rate_percent=rate))

    assert response.status_code == 422
    assert eureka_fake.calls == []  # walidacja przed wywołaniem floty
