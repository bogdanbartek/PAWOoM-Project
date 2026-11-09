import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.main import create_app

CACHE_PREFIX = "lab2:131409:scooter-service-test"
CACHE_TTL = 60


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
def make_client(database_url, monkeypatch):
    """Tworzy klienta HTTP dla nowej instancji aplikacji (z działającym lifespan)."""
    monkeypatch.setenv("CACHE_PREFIX", CACHE_PREFIX)
    monkeypatch.setenv("CACHE_TTL_SECONDS", str(CACHE_TTL))

    def _make(redis_client=None, url=None):
        app = create_app(database_url=url or database_url, redis_client=redis_client or MemoryRedis())
        return TestClient(app)

    return _make


@pytest.fixture
def client(make_client, redis_fake):
    # Świeża baza w tmp_path i pusty zamiennik Redis przy każdym teście.
    with make_client(redis_client=redis_fake) as test_client:
        yield test_client


def cache_key(scooter_id):
    return f"{CACHE_PREFIX}:scooter:{scooter_id}"
