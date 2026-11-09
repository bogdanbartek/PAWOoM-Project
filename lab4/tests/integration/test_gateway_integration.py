"""LAB4: testy integracyjne przez API Gateway (prawdziwe żądania HTTP).

Wymagają działających procesów: Redis, Eureka (:8761), SCOOTER-SERVICE (:8101),
PAYMENT-SERVICE (:8102) i bramki (:8080). Adres bramki: GATEWAY_URL.

Powtarzalność: każdy test tworzy własne rekordy z unikalnym ID (uuid4),
więc ponowne uruchomienie nie kończy się 409, a baza projektu nie jest kasowana.
"""
import os
import uuid

import httpx
import pytest

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8080")


@pytest.fixture
def client():
    with httpx.Client(base_url=GATEWAY_URL, timeout=10.0, trust_env=False) as http:
        yield http


def unique_id() -> int:
    # Dodatnia liczba całkowita mieszcząca się w INTEGER SQLite; inna przy każdym uruchomieniu.
    return uuid.uuid4().int % 900_000_000 + 100_000_000


def create_scooter(client) -> int:
    scooter_id = unique_id()
    response = client.post(
        "/api/scooters",
        json={"id": scooter_id, "name": f"IT-{scooter_id}", "model": "Integration Test"},
    )
    assert response.status_code == 201, response.text
    assert response.headers["x-gateway"] == "lab4"
    return scooter_id


# --- 4 wymagane testy LAB4 ---------------------------------------------------


def test_scooter_read_through_gateway_miss_then_hit(client):
    scooter_id = create_scooter(client)

    first = client.get(f"/api/scooters/{scooter_id}")
    second = client.get(f"/api/scooters/{scooter_id}")

    assert first.status_code == second.status_code == 200
    assert first.json() == {
        "id": scooter_id,
        "name": f"IT-{scooter_id}",
        "model": "Integration Test",
        "status": "available",
    }
    assert first.headers["x-gateway"] == second.headers["x-gateway"] == "lab4"
    # Przy działającym Redis: MISS, potem HIT. Przy awarii Redis oba BYPASS.
    assert first.headers["x-cache"] in {"MISS", "BYPASS"}
    assert second.headers["x-cache"] in {"HIT", "BYPASS"}
    assert second.json() == first.json()


def test_payment_read_through_gateway_uses_lab3_flow(client):
    scooter_id = create_scooter(client)
    payment_id = unique_id()

    created = client.post(
        "/api/payments", json={"id": payment_id, "scooter_id": scooter_id, "amount": 19.99}
    )
    details = client.get(f"/api/payments/{payment_id}/details")

    assert created.status_code == 201, created.text
    assert created.headers["x-gateway"] == "lab4"
    assert details.status_code == 200
    assert details.headers["x-gateway"] == "lab4"
    body = details.json()
    # Dane z obu usług: płatność (PAYMENT-SERVICE) + hulajnoga pobrana z SCOOTER-SERVICE.
    assert body["payment"] == {
        "id": payment_id, "scooter_id": scooter_id, "amount": 19.99, "status": "pending"
    }
    assert body["scooter"]["id"] == scooter_id
    assert body["scooter"]["name"] == f"IT-{scooter_id}"


def test_write_through_gateway_invalidates_cache(client):
    scooter_id = create_scooter(client)
    warm = client.get(f"/api/scooters/{scooter_id}")
    assert warm.json()["status"] == "available"

    rented = client.post(f"/api/scooters/{scooter_id}/rent")
    after_write = client.get(f"/api/scooters/{scooter_id}")
    again = client.get(f"/api/scooters/{scooter_id}")

    assert rented.status_code == 200
    assert rented.headers["x-gateway"] == "lab4"
    assert rented.json()["status"] == "rented"
    assert after_write.json()["status"] == "rented"  # nie stara kopia z cache
    assert after_write.headers["x-cache"] in {"MISS", "BYPASS"}
    assert again.headers["x-cache"] in {"HIT", "BYPASS"}
    assert again.json()["status"] == "rented"


def test_business_rule_409_and_validation_422_forwarded(client):
    scooter_id = create_scooter(client)
    assert client.post(f"/api/scooters/{scooter_id}/rent").status_code == 200

    conflict = client.post(f"/api/scooters/{scooter_id}/rent")
    invalid = client.post("/api/scooters", json={"id": -1, "name": "", "model": "X"})
    state = client.get(f"/api/scooters/{scooter_id}")

    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "Scooter is not available for rental"}
    assert conflict.headers["x-gateway"] == "lab4"
    assert invalid.status_code == 422
    assert "detail" in invalid.json()
    assert invalid.headers["x-gateway"] == "lab4"
    assert state.json()["status"] == "rented"  # odrzucona operacja nie zmieniła stanu


# --- testy dodatkowe ---------------------------------------------------------


def test_domain_404_vs_gateway_404(client):
    missing = client.get(f"/api/scooters/{unique_id()}")
    no_route = client.get("/api/not-a-route")

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Scooter not found"}
    assert missing.headers["x-gateway"] == "lab4"  # trasa dopasowana, brak rekordu w usłudze
    assert no_route.status_code == 404
    assert "x-gateway" not in no_route.headers  # żadna trasa nie pasuje - odpowiada sama bramka


def test_internal_endpoints_are_not_exposed(client):
    for path in ("/api/health", "/api/ready", "/api/docs", "/api/openapi.json"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert "x-gateway" not in response.headers, path


def test_payment_for_missing_scooter_returns_404_through_gateway(client):
    response = client.post(
        "/api/payments", json={"id": unique_id(), "scooter_id": unique_id(), "amount": 5}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Scooter not found"}
    assert response.headers["x-gateway"] == "lab4"


def test_gateway_own_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "API-GATEWAY"}
