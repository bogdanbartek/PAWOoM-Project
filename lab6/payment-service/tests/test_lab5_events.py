"""LAB5: Payment Service jako producent zdarzenia PaymentCompleted (InMemoryEventBroker)."""
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import ROUTING_KEY, create_app
from app.messaging import InMemoryEventBroker
from tests.conftest import FakeEurekaClient, payment_body


def test_pay_publishes_payment_completed_event(client, broker, eureka_fake):
    broker.bind_queue("scooter.payment-events", ROUTING_KEY)  # jak konsument w lifespan
    eureka_fake.response = {**eureka_fake.response, "id": 3}
    created = client.post("/payments", json=payment_body(payment_id=7, scooter_id=3, amount=15.5))
    assert created.status_code == 201
    assert broker.published == []  # utworzenie płatności niczego nie publikuje

    response = client.post("/payments/7/pay")

    assert response.status_code == 200
    assert response.json()["status"] == "paid"
    assert len(broker.published) == 1
    routing_key, event = broker.published[0]
    assert routing_key == "payment.completed"
    assert set(event) == {"event_id", "event_type", "payment_id", "scooter_id", "amount", "occurred_at"}
    assert event["event_type"] == "PaymentCompleted"
    assert event["event_id"].startswith("evt-")
    assert (event["payment_id"], event["scooter_id"], event["amount"]) == (7, 3, 15.5)
    assert datetime.fromisoformat(event["occurred_at"]).utcoffset().total_seconds() == 0  # ISO 8601 UTC
    # Wiadomość trafiła do kolejki związanej kluczem routingu.
    assert list(broker._queues["scooter.payment-events"]) == [event]


def test_rejected_operations_do_not_publish(client, broker, eureka_fake):
    client.post("/payments", json=payment_body())
    client.post("/payments/1/pay")
    broker.published.clear()

    already_paid = client.post("/payments/1/pay")  # 409 - reguła pending -> paid
    missing = client.post("/payments/999/pay")  # 404
    invalid = client.post("/payments/abc/pay")  # 422
    invalid_body = client.post("/payments", json={"id": 2, "scooter_id": 1, "amount": 0})  # 422

    assert already_paid.status_code == 409
    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert invalid_body.status_code == 422
    assert broker.published == []


def test_broker_outage_returns_503_and_payment_stays_pending():
    broker = InMemoryEventBroker(down=True)
    with TestClient(create_app(eureka_client=FakeEurekaClient(), event_broker=broker)) as client:
        assert client.post("/payments", json=payment_body()).status_code == 201

        response = client.post("/payments/1/pay")
        state = client.get("/payments/1")

        broker.down = False  # broker wraca - ponowienie się udaje
        retry = client.post("/payments/1/pay")

    assert response.status_code == 503
    assert response.json() == {"detail": "RabbitMQ broker is unavailable"}
    assert state.json()["status"] == "pending"  # brak "opłaconej" płatności bez zdarzenia
    assert retry.status_code == 200
    assert len(broker.published) == 1


def test_broker_closed_on_shutdown_and_each_pay_has_unique_event_id():
    broker = InMemoryEventBroker()
    with TestClient(create_app(eureka_client=FakeEurekaClient(), event_broker=broker)) as client:
        for payment_id in (1, 2):
            client.post("/payments", json=payment_body(payment_id=payment_id))
            client.post(f"/payments/{payment_id}/pay")
        assert broker.closed is False

    assert broker.closed is True
    ids = [event["event_id"] for _, event in broker.published]
    assert len(ids) == len(set(ids)) == 2
