import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    # Świeża aplikacja i magazyn przy każdym teście.
    with TestClient(create_app()) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    # Zmień oczekiwaną nazwę razem z nazwą swojej usługi.
    assert response.json() == {"status": "ok", "service": "replace-me"}


# Ten test startowy nie zastępuje trzech własnych testów domenowych.
# Dodaj testy zapisu i odczytu, błędnych danych i konfliktu bez zmiany stanu.
# Co najmniej jeden ma sprawdzać twoją regułę biznesową.
