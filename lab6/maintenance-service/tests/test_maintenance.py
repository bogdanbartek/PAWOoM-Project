"""Testy API Maintenance Service — LAB1 (CRUD + reguły) i LAB3 (Eureka)."""
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient

from app.main import SERVICE_NAME, create_app
from tests.conftest import SCOOTER, FakeEurekaClient, job_body


def run(fake, method, path, **kwargs):
    with TestClient(create_app(eureka_client=fake)) as client:
        response = client.request(method, path, **kwargs)
        health = client.get("/health")
        jobs = client.get("/jobs").json()
    return response, health, jobs


def http_error(code):
    return HTTPError("http://scooter/scooters/1", code, "error", {}, None)


# --- health ---

def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": SERVICE_NAME}


# --- CRUD ---

def test_empty_list_on_startup(client):
    assert client.get("/jobs").json() == []


def test_create_then_read(client, eureka_fake):
    created = client.post("/jobs", json=job_body())
    assert created.status_code == 201
    assert created.json() == {
        "id": 1, "scooter_id": 1, "description": "Wymiana opon", "status": "pending"
    }
    assert client.get("/jobs/1").json() == created.json()
    assert len(client.get("/jobs").json()) == 1


def test_not_found_returns_404(client):
    response = client.get("/jobs/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Maintenance job not found"}


def test_invalid_body_returns_422(client):
    bad = client.post("/jobs", json={"id": 0, "scooter_id": 1, "description": "X"})
    assert bad.status_code == 422
    assert client.get("/jobs").json() == []


def test_duplicate_id_returns_409(client, eureka_fake):
    client.post("/jobs", json=job_body(description="Pierwsza"))
    duplicate = client.post("/jobs", json=job_body(description="Duplikat"))
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Job with this ID already exists"}
    assert client.get("/jobs/1").json()["description"] == "Pierwsza"
    assert len(eureka_fake.calls) == 1  # duplikat odrzucony przed wywołaniem Eureki


# --- maszyna stanów: pending → in_progress → completed ---

def test_full_lifecycle(client, eureka_fake):
    client.post("/jobs", json=job_body())

    started = client.post("/jobs/1/start")
    assert started.status_code == 200
    assert started.json()["status"] == "in_progress"

    completed = client.post("/jobs/1/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    assert client.get("/jobs/1").json()["status"] == "completed"


def test_cannot_start_completed_job(client, eureka_fake):
    client.post("/jobs", json=job_body())
    client.post("/jobs/1/start")
    client.post("/jobs/1/complete")

    response = client.post("/jobs/1/start")
    assert response.status_code == 409
    assert "in_progress" in response.json()["detail"] or "completed" in response.json()["detail"]


def test_cannot_complete_pending_job(client, eureka_fake):
    client.post("/jobs", json=job_body())

    response = client.post("/jobs/1/complete")
    assert response.status_code == 409
    assert "pending" in response.json()["detail"]


def test_cannot_start_already_in_progress(client, eureka_fake):
    client.post("/jobs", json=job_body())
    client.post("/jobs/1/start")

    response = client.post("/jobs/1/start")
    assert response.status_code == 409


def test_operations_on_missing_job_return_404(client):
    assert client.post("/jobs/999/start").status_code == 404
    assert client.post("/jobs/999/complete").status_code == 404


# --- LAB3: Eureka ---

def test_create_job_discovers_scooter_service_by_name():
    fake = FakeEurekaClient()
    response, _, jobs = run(fake, "POST", "/jobs", json=job_body())

    assert response.status_code == 201
    assert fake.calls == [("SCOOTER-SERVICE", "/scooters/1", "json", 3)]
    assert fake.starts == fake.stops == 1


def test_create_job_for_missing_scooter_returns_404():
    fake = FakeEurekaClient(error=http_error(404))
    response, _, jobs = run(fake, "POST", "/jobs", json=job_body(scooter_id=999))

    assert response.status_code == 404
    assert response.json() == {"detail": "Scooter not found"}
    assert jobs == []


@pytest.mark.parametrize("error", [URLError("connection refused"), TimeoutError("timed out")])
def test_create_job_returns_503_when_scooter_service_is_down(error):
    fake = FakeEurekaClient(error=error)
    response, health, jobs = run(fake, "POST", "/jobs", json=job_body())

    assert response.status_code == 503
    assert response.json() == {"detail": "Scooter Service is unavailable"}
    assert health.status_code == 200
    assert jobs == []


def test_job_details_reads_current_scooter(client, eureka_fake):
    client.post("/jobs", json=job_body())
    eureka_fake.response = {**SCOOTER, "status": "maintenance"}

    response = client.get("/jobs/1/details")

    assert response.status_code == 200
    assert response.json()["job"]["id"] == 1
    assert response.json()["scooter"]["status"] == "maintenance"
    assert eureka_fake.calls[-1] == ("SCOOTER-SERVICE", "/scooters/1", "json", 3)


def test_job_details_missing_job_returns_404_without_calling_dependency(client, eureka_fake):
    response = client.get("/jobs/999/details")
    assert response.status_code == 404
    assert eureka_fake.calls == []
