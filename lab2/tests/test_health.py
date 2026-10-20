import pytest
from fastapi.testclient import TestClient

from app.main import create_app


SCOOTER = {"id": 1, "name": "Hulajnoga 1", "model": "Xiaomi Mi 4 Pro"}


@pytest.fixture
def client():
    # Świeża aplikacja i magazyn przy każdym teście.
    with TestClient(create_app()) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Scooter Rental Service"}


def test_list_and_detail(client):
    response = client.get("/scooters")
    assert response.status_code == 200
    assert response.json() == []

    assert client.post("/scooters", json=SCOOTER).status_code == 201

    response = client.get("/scooters")
    assert response.status_code == 200
    assert response.json() == [{**SCOOTER, "status": "available"}]

    response = client.get("/scooters/1")
    assert response.status_code == 200
    assert response.json() == {**SCOOTER, "status": "available"}


def test_create_then_read(client):
    response = client.post("/scooters", json=SCOOTER)
    assert response.status_code == 201
    assert response.json() == {**SCOOTER, "status": "available"}

    response = client.get("/scooters/1")
    assert response.status_code == 200
    assert response.json() == {**SCOOTER, "status": "available"}


def test_not_found(client):
    response = client.get("/scooters/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Scooter not found"}


def test_invalid_data_leaves_state_unchanged(client):
    response = client.post("/scooters", json={"id": 0, "name": "", "model": "X"})
    assert response.status_code == 422
    error_fields = {tuple(error["loc"]) for error in response.json()["detail"]}
    assert ("body", "id") in error_fields
    assert ("body", "name") in error_fields

    assert client.get("/scooters").json() == []


def test_duplicate_id_conflict_keeps_original(client):
    assert client.post("/scooters", json=SCOOTER).status_code == 201

    response = client.post(
        "/scooters", json={"id": 1, "name": "Inna nazwa", "model": "Segway Ninebot"}
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "Scooter with this ID already exists"}

    response = client.get("/scooters/1")
    assert response.json()["name"] == "Hulajnoga 1"
    assert response.json()["model"] == "Xiaomi Mi 4 Pro"
    assert len(client.get("/scooters").json()) == 1


def test_rent_and_return_rules(client):
    client.post("/scooters", json=SCOOTER)

    # Dozwolone: available -> rented.
    response = client.post("/scooters/1/rent")
    assert response.status_code == 200
    assert response.json()["status"] == "rented"

    # Niedozwolone: ponowne wypożyczenie, stan bez zmian.
    response = client.post("/scooters/1/rent")
    assert response.status_code == 409
    assert response.json() == {"detail": "Scooter is not available for rental"}
    assert client.get("/scooters/1").json()["status"] == "rented"

    # Dozwolone: rented -> available.
    response = client.post("/scooters/1/return")
    assert response.status_code == 200
    assert response.json()["status"] == "available"

    # Niedozwolone: zwrot niewypożyczonej, stan bez zmian.
    response = client.post("/scooters/1/return")
    assert response.status_code == 409
    assert response.json() == {"detail": "Scooter is not currently rented"}
    assert client.get("/scooters/1").json()["status"] == "available"


def test_rent_and_return_missing_scooter(client):
    assert client.post("/scooters/999/rent").status_code == 404
    assert client.post("/scooters/999/return").status_code == 404
