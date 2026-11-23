"""LAB1: podstawowe testy API — health, CRUD, reguły biznesowe."""
import pytest
from fastapi.testclient import TestClient

from app.main import SERVICE_NAME, create_app
from app.messaging import InMemoryEventBroker
from tests.conftest import SCOOTER, FakeEurekaClient, insurance_body


def run(fake, method, path, **kwargs):
    """Uruchamia aplikację z zamiennikiem i wykonuje jedno żądanie."""
    with TestClient(create_app(eureka_client=fake, event_broker=InMemoryEventBroker())) as client:
        response = client.request(method, path, **kwargs)
        health = client.get("/health")
        insurances = client.get("/insurances").json()
    return response, health, insurances


# --- health ---


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": SERVICE_NAME}


# --- lista i szczegóły ---


def test_empty_list_on_startup(client):
    assert client.get("/insurances").json() == []


def test_create_then_read(client, eureka_fake):
    created = client.post("/insurances", json=insurance_body())
    assert created.status_code == 201
    assert created.json() == {"id": 1, "scooter_id": 1, "rate_percent": 5.0, "status": "active"}

    detail = client.get("/insurances/1")
    assert detail.status_code == 200
    assert detail.json() == created.json()

    listing = client.get("/insurances")
    assert len(listing.json()) == 1


def test_not_found_returns_404(client):
    assert client.get("/insurances/999").status_code == 404
    assert client.get("/insurances/999").json() == {"detail": "Insurance not found"}


def test_invalid_body_returns_422(client):
    bad = client.post("/insurances", json={"id": 0, "scooter_id": 1, "rate_percent": 5.0})
    assert bad.status_code == 422
    assert client.get("/insurances").json() == []  # stan bez zmian


def test_duplicate_id_returns_409_keeps_original(client, eureka_fake):
    client.post("/insurances", json=insurance_body(rate_percent=5.0))
    duplicate = client.post("/insurances", json=insurance_body(rate_percent=9.0))
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Insurance with this ID already exists"}
    assert client.get("/insurances/1").json()["rate_percent"] == 5.0
    # duplikat odrzucony przed wywołaniem Eureki (drugi raz)
    assert len(eureka_fake.calls) == 1


# --- reguła: anulowanie ---


def test_cancel_active_insurance(client, eureka_fake):
    client.post("/insurances", json=insurance_body())

    response = client.post("/insurances/1/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert client.get("/insurances/1").json()["status"] == "cancelled"


def test_cancel_already_cancelled_returns_409(client, eureka_fake):
    client.post("/insurances", json=insurance_body())
    client.post("/insurances/1/cancel")

    response = client.post("/insurances/1/cancel")

    assert response.status_code == 409
    assert response.json() == {"detail": "Insurance is already cancelled"}


def test_cancel_missing_insurance_returns_404(client):
    assert client.post("/insurances/999/cancel").status_code == 404
