"""LAB3: cykl życia klienta Eureka w Scooter Rental Service (bez prawdziwego rejestru)."""
from app import eureka as app_eureka
from app.eureka import create_eureka_client
from app.main import EUREKA_APP_NAME, create_app
from tests.conftest import MemoryRedis


def test_eureka_client_started_and_stopped_with_storage(database_url, monkeypatch):
    monkeypatch.setenv("CACHE_PREFIX", "lab3:131409:scooter-service-test")
    events = []

    class OrderedFake:
        async def start(self):
            # Zasoby LAB2 muszą już istnieć, gdy instancja zgłasza się do rejestru.
            events.append(("start", hasattr(app.state, "repository")))

        async def stop(self):
            events.append(("stop", None))

    redis = MemoryRedis()
    closed = []
    redis.close = lambda: closed.append(len(events))

    app = create_app(database_url=database_url, redis_client=redis, eureka_client=OrderedFake())
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert app.state.eureka_client is not None

    assert events == [("start", True), ("stop", None)]
    # Redis zamknięty dopiero po stop() klienta Eureka (wyrejestrowanie przed zamknięciem zasobów).
    assert closed == [2]


def test_lab2_api_still_works_with_fake_registry(client, eureka_fake):
    created = client.post("/scooters", json={"id": 7, "name": "Hulajnoga 7", "model": "Segway"})
    assert created.status_code == 201
    response = client.get("/scooters/7")
    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert eureka_fake.starts == 1
    assert eureka_fake.stops == 0  # klient zatrzymywany dopiero przy zamknięciu aplikacji
    assert eureka_fake.calls == []  # usługa floty nie wywołuje innych usług


def test_eureka_client_configuration_from_environment(monkeypatch):
    monkeypatch.setenv("EUREKA_SERVER_URL", "http://127.0.0.1:8761")
    monkeypatch.setenv("SERVICE_NAME", "SCOOTER-SERVICE")
    monkeypatch.setenv("SERVICE_PORT", "8111")
    monkeypatch.setenv("INSTANCE_IP", "127.0.0.1")
    monkeypatch.setenv("INSTANCE_HOST", "localhost")

    captured = {}
    monkeypatch.setattr(app_eureka, "EurekaClient", lambda **kwargs: captured.update(kwargs))

    create_eureka_client(EUREKA_APP_NAME, 8101)  # tylko konstrukcja, bez sieci

    assert captured == {
        "eureka_server": "http://127.0.0.1:8761",
        "eureka_context": "/eureka",
        "app_name": "SCOOTER-SERVICE",
        "instance_ip": "127.0.0.1",
        "instance_host": "localhost",
        "instance_port": 8111,
        "strict_service_error_policy": False,
    }


def test_eureka_client_defaults_use_logical_name_and_port(monkeypatch):
    for name in ("EUREKA_SERVER_URL", "SERVICE_NAME", "SERVICE_PORT", "INSTANCE_IP", "INSTANCE_HOST"):
        monkeypatch.delenv(name, raising=False)
    captured = {}
    monkeypatch.setattr(app_eureka, "EurekaClient", lambda **kwargs: captured.update(kwargs))

    create_eureka_client(EUREKA_APP_NAME, 8101)

    assert captured["app_name"] == "SCOOTER-SERVICE"
    assert captured["instance_port"] == 8101
    assert captured["instance_ip"] != "0.0.0.0"
