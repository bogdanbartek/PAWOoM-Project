"""LAB3: Payment Service - odnajdywanie SCOOTER-SERVICE po nazwie i mapowanie błędów zależności."""
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.messaging import InMemoryEventBroker
from tests.conftest import SCOOTER, FakeEurekaClient, payment_body


def run(fake, method, path, **kwargs):
    """Uruchamia aplikację z zamiennikiem (pełny lifespan) i wykonuje jedno żądanie."""
    with TestClient(create_app(eureka_client=fake, event_broker=InMemoryEventBroker())) as client:
        response = client.request(method, path, **kwargs)
        health = client.get("/health")
        payments = client.get("/payments").json()
    return response, health, payments


def http_error(code):
    return HTTPError("http://scooter/scooters/1", code, "error", {}, None)


# --- 4 wymagane testy LAB3 ---------------------------------------------------


def test_create_payment_discovers_scooter_service_by_name():
    fake = FakeEurekaClient()

    response, _, payments = run(fake, "POST", "/payments", json=payment_body())

    assert response.status_code == 201
    assert response.json() == {"id": 1, "scooter_id": 1, "amount": 12.5, "status": "pending"}
    assert fake.calls == [("SCOOTER-SERVICE", "/scooters/1", "json", 3)]
    assert payments == [response.json()]
    assert fake.starts == fake.stops == 1


def test_create_payment_for_missing_scooter_returns_404_and_stores_nothing():
    fake = FakeEurekaClient(error=http_error(404))

    response, _, payments = run(fake, "POST", "/payments", json=payment_body(scooter_id=999))

    assert response.status_code == 404
    assert response.json() == {"detail": "Scooter not found"}
    assert fake.calls == [("SCOOTER-SERVICE", "/scooters/999", "json", 3)]
    assert payments == []


@pytest.mark.parametrize("error", [URLError("connection refused"), TimeoutError("timed out")])
def test_create_payment_returns_503_when_scooter_service_is_down(error):
    fake = FakeEurekaClient(error=error)

    response, health, payments = run(fake, "POST", "/payments", json=payment_body())

    assert response.status_code == 503
    assert response.json() == {"detail": "Scooter Service is unavailable"}
    assert health.status_code == 200  # usługa płatności żyje mimo awarii zależności
    assert payments == []  # nie powstaje płatność za niepotwierdzoną hulajnogę
    assert fake.starts == fake.stops == 1


@pytest.mark.parametrize("code", [500, 400, 409])
def test_other_dependency_http_error_maps_to_502(code):
    fake = FakeEurekaClient(error=http_error(code))

    response, _, payments = run(fake, "POST", "/payments", json=payment_body())

    assert response.status_code == 502
    assert response.json() == {"detail": "Scooter Service returned an HTTP error"}
    assert payments == []


# --- testy dodatkowe ---------------------------------------------------------


def test_invalid_dependency_response_maps_to_502():
    fake = FakeEurekaClient(response={"id": 2, "name": "inna"})  # inna hulajnoga niż żądana

    response, _, payments = run(fake, "POST", "/payments", json=payment_body(scooter_id=1))

    assert response.status_code == 502
    assert response.json() == {"detail": "Scooter Service returned an invalid response"}
    assert payments == []


def test_invalid_body_returns_422_without_calling_dependency():
    fake = FakeEurekaClient()

    response, _, payments = run(fake, "POST", "/payments", json={"id": 1, "scooter_id": 1, "amount": -5})

    assert response.status_code == 422
    assert fake.calls == []
    assert payments == []


def test_duplicate_payment_returns_409_and_keeps_original(client, eureka_fake):
    assert client.post("/payments", json=payment_body(amount=10)).status_code == 201

    duplicate = client.post("/payments", json=payment_body(amount=99))

    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Payment with this ID already exists"}
    assert client.get("/payments/1").json()["amount"] == 10
    assert len(eureka_fake.calls) == 1  # duplikat odrzucony przed wywołaniem zależności


def test_pay_rule_pending_to_paid_only_once(client):
    client.post("/payments", json=payment_body())

    paid = client.post("/payments/1/pay")
    again = client.post("/payments/1/pay")

    assert paid.status_code == 200
    assert paid.json()["status"] == "paid"
    assert again.status_code == 409
    assert again.json() == {"detail": "Payment is already paid"}
    assert client.get("/payments/1").json()["status"] == "paid"


def test_missing_payment_returns_404(client, eureka_fake):
    assert client.get("/payments/42").status_code == 404
    assert client.post("/payments/42/pay").status_code == 404
    response = client.get("/payments/42/details")
    assert response.status_code == 404
    assert response.json() == {"detail": "Payment not found"}
    assert eureka_fake.calls == []


def test_payment_details_reads_current_scooter_from_dependency(client, eureka_fake):
    client.post("/payments", json=payment_body())
    eureka_fake.response = {**SCOOTER, "status": "rented"}  # stan zmienił się w usłudze floty

    response = client.get("/payments/1/details")

    assert response.status_code == 200
    assert response.json() == {
        "payment": {"id": 1, "scooter_id": 1, "amount": 12.5, "status": "pending"},
        "scooter": {**SCOOTER, "status": "rented"},
    }
    assert eureka_fake.calls[-1] == ("SCOOTER-SERVICE", "/scooters/1", "json", 3)


def test_payment_details_returns_503_but_payment_still_readable(client, eureka_fake):
    client.post("/payments", json=payment_body())
    eureka_fake.error = URLError("connection refused")

    assert client.get("/payments/1/details").status_code == 503
    assert client.get("/payments/1").status_code == 200  # własne dane dostępne bez zależności
