import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.main import create_app

CACHE_PREFIX = "lab3:131409:scooter-service-test"
CACHE_TTL = 60


class FakeEurekaClient:
    """Zamiennik klienta Eureka (LAB3): liczy start/stop, nie łączy się z siecią."""

    def __init__(self):
        self.starts = 0
        self.stops = 0
        self.calls = []

    async def start(self):
        self.starts += 1

    async def stop(self):
        self.stops += 1

    async def do_service(self, service_name, path, return_type=None, timeout=None):
        self.calls.append((service_name, path, return_type, timeout))
        raise AssertionError("Scooter Service does not call other services")


class MemoryRedis:
    """Zamiennik Redis tylko do testów (z pakietu LAB2). Nie symuluje upływu TTL."""

    def __init__(self):
        self.values = {}
        self.expirations = {}
        self.down = False

    def check(self):
        if self.down:
            raise ConnectionError("Simulated outage")

    def get(self, key):
        self.check()
        return self.values.get(key)

    def set(self, key, value, ex):
        self.check()
        self.values[key] = value
        self.expirations[key] = ex

    def delete(self, key):
        self.check()
        self.values.pop(key, None)
        self.expirations.pop(key, None)

    def ping(self):
        self.check()
        return True

    def close(self):
        pass


@pytest.fixture
def database_url(tmp_path):
    return "sqlite:///" + (tmp_path / "test.db").as_posix()


@pytest.fixture
def redis_fake():
    return MemoryRedis()


@pytest.fixture
def eureka_fake():
    return FakeEurekaClient()


@pytest.fixture
def make_client(database_url, monkeypatch, eureka_fake):
    """Tworzy klienta HTTP dla nowej instancji aplikacji (z działającym lifespan)."""
    monkeypatch.setenv("CACHE_PREFIX", CACHE_PREFIX)
    monkeypatch.setenv("CACHE_TTL_SECONDS", str(CACHE_TTL))

    def _make(redis_client=None, url=None, eureka_client=None):
        app = create_app(
            database_url=url or database_url,
            redis_client=redis_client or MemoryRedis(),
            eureka_client=eureka_client or eureka_fake,
        )
        return TestClient(app)

    return _make


@pytest.fixture
def client(make_client, redis_fake):
    # Świeża baza w tmp_path i pusty zamiennik Redis przy każdym teście.
    with make_client(redis_client=redis_fake) as test_client:
        yield test_client


def cache_key(scooter_id):
    return f"{CACHE_PREFIX}:scooter:{scooter_id}"
