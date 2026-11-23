"""LAB3: Insurance Service - odnajdywanie SCOOTER-SERVICE po nazwie i mapowanie błędów."""
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.messaging import InMemoryEventBroker
from tests.conftest import SCOOTER, FakeEurekaClient, insurance_body


def run(fake, method, path, **kwargs):
    with TestClient(create_app(eureka_client=fake, event_broker=InMemoryEventBroker())) as client:
        response = client.request(method, path, **kwargs)
        health = client.get("/health")
        insurances = client.get("/insurances").json()
    return response, health, insurances


def http_error(code):
    return HTTPError("http://scooter/scooters/1", code, "error", {}, None)


def test_create_insurance_discovers_scooter_service_by_name():
    fake = FakeEurekaClient()
    response, _, insurances = run(fake, "POST", "/insurances", json=insurance_body())

    assert response.status_code == 201
    assert response.json() == {"id": 1, "scooter_id": 1, "rate_percent": 5.0, "status": "active"}
    assert fake.calls == [("SCOOTER-SERVICE", "/scooters/1", "json", 3)]
    assert insurances == [response.json()]
    assert fake.starts == fake.stops == 1


def test_create_insurance_for_missing_scooter_returns_404():
    fake = FakeEurekaClient(error=http_error(404))
    response, _, insurances = run(fake, "POST", "/insurances", json=insurance_body(scooter_id=999))

    assert response.status_code == 404
    assert response.json() == {"detail": "Scooter not found"}
    assert insurances == []


@pytest.mark.parametrize("error", [URLError("connection refused"), TimeoutError("timed out")])
def test_create_insurance_returns_503_when_scooter_service_is_down(error):
    fake = FakeEurekaClient(error=error)
    response, health, insurances = run(fake, "POST", "/insurances", json=insurance_body())

    assert response.status_code == 503
    assert response.json() == {"detail": "Scooter Service is unavailable"}
    assert health.status_code == 200  # usługa ubezpieczeń żyje mimo awarii zależności
    assert insurances == []


@pytest.mark.parametrize("code", [500, 400, 409])
def test_other_dependency_error_maps_to_502(code):
    fake = FakeEurekaClient(error=http_error(code))
    response, _, insurances = run(fake, "POST", "/insurances", json=insurance_body())

    assert response.status_code == 502
    assert insurances == []


def test_insurance_details_reads_current_scooter_from_dependency(client, eureka_fake):
    client.post("/insurances", json=insurance_body())
    eureka_fake.response = {**SCOOTER, "status": "rented"}

    response = client.get("/insurances/1/details")

    assert response.status_code == 200
    assert response.json() == {
        "insurance": {"id": 1, "scooter_id": 1, "rate_percent": 5.0, "status": "active"},
        "scooter": {**SCOOTER, "status": "rented"},
    }


def test_insurance_details_missing_returns_404_without_calling_dependency(client, eureka_fake):
    response = client.get("/insurances/999/details")
    assert response.status_code == 404
    assert eureka_fake.calls == []
