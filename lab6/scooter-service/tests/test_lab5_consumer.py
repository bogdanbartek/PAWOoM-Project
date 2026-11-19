"""LAB5: Scooter Rental Service jako idempotentny konsument PaymentCompleted (InMemoryEventBroker)."""
from app.events import QUEUE_NAME, ROUTING_KEY
from tests.conftest import CACHE_PREFIX, MemoryRedis

SCOOTER = {"id": 1, "name": "Hulajnoga 1", "model": "Xiaomi Mi 4 Pro"}
CONSUME = "/scooters/payment-events/consume"


def summary_key(scooter_id):
    return f"{CACHE_PREFIX}:scooter-payment-summary:{scooter_id}"


def payment_completed(event_id="evt-000000000001", payment_id=10, scooter_id=1, amount=12.5, **extra):
    return {
        "event_id": event_id,
        "event_type": "PaymentCompleted",
        "payment_id": payment_id,
        "scooter_id": scooter_id,
        "amount": amount,
        "occurred_at": "2026-11-09T12:00:00+00:00",
        **extra,
    }


# --- wymagane testy LAB5 -----------------------------------------------------


def test_consumer_binds_queue_processes_event_and_invalidates_cache(client, broker, redis_fake):
    assert broker._bindings[ROUTING_KEY] == [QUEUE_NAME]  # bind_queue w lifespan
    client.post("/scooters", json=SCOOTER)
    before = client.get("/scooters/1/payment-summary")
    assert before.headers["X-Cache"] == "MISS"
    assert before.json() == {
        "scooter_id": 1, "paid_payments_count": 0, "total_paid_amount": 0.0,
        "last_payment_id": None, "last_paid_at": None,
    }
    assert client.get("/scooters/1/payment-summary").headers["X-Cache"] == "HIT"
    assert summary_key(1) in redis_fake.values

    broker.publish(ROUTING_KEY, payment_completed())
    consumed = client.post(CONSUME)

    assert consumed.status_code == 200
    assert consumed.json() == {
        "queue": QUEUE_NAME, "consumed_messages": 1, "applied_events": 1,
        "duplicate_events": 0, "ignored_events": 0, "unique_events_processed": 1,
    }
    assert summary_key(1) not in redis_fake.values  # unieważnione po commicie
    after = client.get("/scooters/1/payment-summary")
    assert after.headers["X-Cache"] == "MISS"
    assert after.json() == {
        "scooter_id": 1, "paid_payments_count": 1, "total_paid_amount": 12.5,
        "last_payment_id": 10, "last_paid_at": "2026-11-09T12:00:00+00:00",
    }
    assert client.get("/scooters/1/payment-summary").headers["X-Cache"] == "HIT"
    assert list(broker._queues[QUEUE_NAME]) == []  # wiadomość potwierdzona i zdjęta z kolejki


def test_duplicate_event_id_is_applied_exactly_once(client, broker):
    client.post("/scooters", json=SCOOTER)
    event = payment_completed(event_id="evt-dup-000001", amount=20)
    broker.publish(ROUTING_KEY, event)
    broker.publish(ROUTING_KEY, event)

    first = client.post(CONSUME).json()
    broker.publish(ROUTING_KEY, event)  # trzecie dostarczenie w osobnym wywołaniu
    second = client.post(CONSUME).json()

    assert (first["consumed_messages"], first["applied_events"], first["duplicate_events"]) == (2, 1, 1)
    assert (second["consumed_messages"], second["applied_events"], second["duplicate_events"]) == (1, 0, 1)
    assert second["unique_events_processed"] == 1
    summary = client.get("/scooters/1/payment-summary").json()
    assert summary["paid_payments_count"] == 1
    assert summary["total_paid_amount"] == 20.0


def test_processed_event_ids_survive_restart(make_client, broker):
    """Idempotentność w SQLite, nie w pamięci procesu: nowa instancja dalej rozpoznaje duplikat."""
    event = payment_completed(event_id="evt-restart-001")
    with make_client(redis_client=MemoryRedis()) as first:
        first.post("/scooters", json=SCOOTER)
        broker.publish(ROUTING_KEY, event)
        assert first.post(CONSUME).json()["applied_events"] == 1

    with make_client(redis_client=MemoryRedis()) as second:  # ta sama baza, nowy pusty cache
        broker.publish(ROUTING_KEY, event)
        result = second.post(CONSUME).json()
        summary = second.get("/scooters/1/payment-summary").json()

    assert (result["applied_events"], result["duplicate_events"]) == (0, 1)
    assert summary["paid_payments_count"] == 1


def test_broker_outage_returns_503_and_keeps_state(client, broker):
    client.post("/scooters", json=SCOOTER)
    broker.publish(ROUTING_KEY, payment_completed())
    broker.down = True

    response = client.post(CONSUME)
    summary = client.get("/scooters/1/payment-summary").json()

    assert response.status_code == 503
    assert response.json() == {"detail": "RabbitMQ broker is unavailable"}
    assert summary["paid_payments_count"] == 0
    broker.down = False
    assert client.post(CONSUME).json()["applied_events"] == 1  # wiadomość czekała w kolejce


# --- testy dodatkowe ---------------------------------------------------------


def test_invalid_event_is_rejected_requeued_and_changes_nothing(client, broker):
    client.post("/scooters", json=SCOOTER)
    bad = {"event_type": "PaymentCompleted", "scooter_id": 1, "amount": 5}  # brak event_id
    broker.publish(ROUTING_KEY, bad)

    response = client.post(CONSUME)

    assert response.status_code == 422
    assert "event_id" in response.json()["detail"]
    assert list(broker._queues[QUEUE_NAME]) == [bad]  # NACK -> wiadomość nadal w kolejce
    assert client.get("/scooters/1/payment-summary").json()["paid_payments_count"] == 0


def test_event_for_unknown_scooter_is_rejected_without_changes(client, broker):
    broker.publish(ROUTING_KEY, payment_completed(scooter_id=999))

    response = client.post(CONSUME)

    assert response.status_code == 422
    assert client.post("/scooters", json=SCOOTER).status_code == 201
    assert client.get("/scooters/1/payment-summary").json()["paid_payments_count"] == 0


def test_tolerant_reader_ignores_unknown_fields_and_other_event_types(client, broker):
    client.post("/scooters", json=SCOOTER)
    broker.publish(ROUTING_KEY, payment_completed(currency="PLN", schema_version=2, customer={"x": 1}))
    broker.publish(ROUTING_KEY, {"event_id": "evt-other-1", "event_type": "PaymentRefunded", "scooter_id": 1})

    result = client.post(CONSUME).json()

    assert (result["consumed_messages"], result["applied_events"], result["ignored_events"]) == (2, 1, 1)
    assert client.get("/scooters/1/payment-summary").json()["paid_payments_count"] == 1


def test_payment_summary_404_for_missing_scooter_and_scooter_record_untouched(client, broker):
    assert client.get("/scooters/5/payment-summary").status_code == 404
    client.post("/scooters", json=SCOOTER)
    client.post("/scooters/1/rent")
    broker.publish(ROUTING_KEY, payment_completed())
    client.post(CONSUME)

    # Kontrakt LAB1 bez zmian: rekord hulajnogi nie dostał nowych pól.
    assert client.get("/scooters/1").json() == {**SCOOTER, "status": "rented"}


def test_two_events_accumulate_amounts(client, broker):
    client.post("/scooters", json=SCOOTER)
    broker.publish(ROUTING_KEY, payment_completed(event_id="evt-a", payment_id=1, amount=10.1))
    broker.publish(ROUTING_KEY, payment_completed(event_id="evt-b", payment_id=2, amount=0.2))

    client.post(CONSUME)
    summary = client.get("/scooters/1/payment-summary").json()

    assert summary["paid_payments_count"] == 2
    assert summary["total_paid_amount"] == 10.3
    assert summary["last_payment_id"] == 2


def test_rabbit_broker_maps_connection_failure_to_broker_unavailable(monkeypatch):
    """Regresja: konfiguracja parametrów pika nie może rzucać AttributeError przy starcie."""
    import pika
    import pytest

    from app.messaging import BrokerUnavailableError, RabbitEventBroker

    seen = {}

    def refuse(params):
        seen["params"] = params
        raise pika.exceptions.AMQPConnectionError("refused")

    monkeypatch.setattr(pika, "BlockingConnection", refuse)
    broker = RabbitEventBroker("amqp://guest:guest@127.0.0.1:5672/%2F")

    with pytest.raises(BrokerUnavailableError):
        broker.bind_queue(QUEUE_NAME, ROUTING_KEY)
    assert seen["params"].socket_timeout == 2.0
    assert seen["params"].blocked_connection_timeout == 2.0
