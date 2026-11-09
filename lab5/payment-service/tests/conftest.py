import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.messaging import InMemoryEventBroker

SCOOTER = {"id": 1, "name": "Hulajnoga 1", "model": "Xiaomi Mi 4 Pro", "status": "available"}


class FakeEurekaClient:
    """Zamiennik klienta Eureka: bez rejestru i bez sieci.

    `response` - odpowiedź zależności, `error` - wyjątek rzucany przez do_service.
    Zapisuje wywołania (nazwa usługi, ścieżka, return_type, timeout) oraz start/stop.
    """

    def __init__(self, response=None, error=None):
        self.response = response if response is not None else dict(SCOOTER)
        self.error = error
        self.calls = []
        self.starts = 0
        self.stops = 0

    async def start(self):
        self.starts += 1

    async def stop(self):
        self.stops += 1

    async def do_service(self, service_name, path, return_type=None, timeout=None):
        self.calls.append((service_name, path, return_type, timeout))
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture
def eureka_fake():
    return FakeEurekaClient()


@pytest.fixture
def broker():
    """LAB5: broker w pamięci - testy nie łączą się z RabbitMQ."""
    return InMemoryEventBroker()


@pytest.fixture
def client(eureka_fake, broker):
    with TestClient(create_app(eureka_client=eureka_fake, event_broker=broker)) as test_client:
        yield test_client


def payment_body(payment_id=1, scooter_id=1, amount=12.5):
    return {"id": payment_id, "scooter_id": scooter_id, "amount": amount}
