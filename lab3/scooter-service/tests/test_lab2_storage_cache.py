"""Testy LAB2: trwałość w SQLite, cache-aside w Redis (zamiennik MemoryRedis)."""
import pytest

from conftest import CACHE_TTL, MemoryRedis, cache_key

SCOOTER = {"id": 7, "name": "Hulajnoga 7", "model": "Segway Ninebot G30"}


# --- 1. Trwałość ------------------------------------------------------------

def test_data_survives_new_app_instance_with_empty_cache(make_client):
    # Instancja 1: zapis i zmiana statusu.
    with make_client(redis_client=MemoryRedis()) as first:
        assert first.post("/scooters", json=SCOOTER).status_code == 201
        assert first.post("/scooters/7/rent").status_code == 200
    # Wyjście z `with` = koniec lifespan: klient Redis zamknięty, engine.dispose().

    # Instancja 2: ta sama baza, NOWY pusty Redis -> odczyt musi pochodzić z bazy.
    fresh_redis = MemoryRedis()
    with make_client(redis_client=fresh_redis) as second:
        response = second.get("/scooters/7")
        assert response.status_code == 200
        assert response.headers["X-Cache"] == "MISS"
        assert response.json() == {**SCOOTER, "status": "rented"}
        assert second.get("/scooters").json() == [{**SCOOTER, "status": "rented"}]


# --- 2. MISS -> HIT, repozytorium nie jest wołane przy HIT --------------------

def test_miss_then_hit_does_not_touch_repository(client, redis_fake, monkeypatch):
    client.post("/scooters", json=SCOOTER)

    repository = client.app.state.repository
    reads = []
    original_get = repository.get

    def counted_get(scooter_id):
        reads.append(scooter_id)
        return original_get(scooter_id)

    monkeypatch.setattr(repository, "get", counted_get)

    first = client.get("/scooters/7")
    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert redis_fake.expirations[cache_key(7)] == CACHE_TTL  # zapis z TTL

    second = client.get("/scooters/7")
    assert second.status_code == 200
    assert second.headers["X-Cache"] == "HIT"
    assert second.json() == first.json() == {**SCOOTER, "status": "available"}

    assert reads == [7]  # baza czytana tylko przy MISS


# --- 3. Unieważnienie po zmianie przez API ----------------------------------

def test_rent_and_return_invalidate_cache(client, redis_fake):
    client.post("/scooters", json=SCOOTER)
    assert client.get("/scooters/7").headers["X-Cache"] == "MISS"
    assert cache_key(7) in redis_fake.values

    assert client.post("/scooters/7/rent").status_code == 200
    assert cache_key(7) not in redis_fake.values  # kopia usunięta po commicie

    response = client.get("/scooters/7")
    assert response.headers["X-Cache"] == "MISS"
    assert response.json()["status"] == "rented"  # nowa wartość, nie stara kopia
    assert client.get("/scooters/7").headers["X-Cache"] == "HIT"

    assert client.post("/scooters/7/return").status_code == 200
    response = client.get("/scooters/7")
    assert response.headers["X-Cache"] == "MISS"
    assert response.json()["status"] == "available"


# --- 4. Awaria cache --------------------------------------------------------

def test_cache_outage_bypasses_and_still_commits(client, redis_fake):
    client.post("/scooters", json=SCOOTER)
    redis_fake.down = True

    response = client.get("/scooters/7")
    assert response.status_code == 200
    assert response.headers["X-Cache"] == "BYPASS"

    # Zapis działa mimo awarii Redis (nieudane DELETE nie cofa commitu).
    assert client.post("/scooters/7/rent").status_code == 200
    response = client.get("/scooters/7")
    assert response.headers["X-Cache"] == "BYPASS"
    assert response.json()["status"] == "rented"
    assert client.app.state.repository.get(7).status == "rented"


# --- Testy dodatkowe ----------------------------------------------------------

def test_failed_cache_set_returns_database_value_as_bypass(client, redis_fake, monkeypatch):
    client.post("/scooters", json=SCOOTER)

    def failing_set(*args, **kwargs):
        from redis.exceptions import ConnectionError
        raise ConnectionError("SET failed")

    monkeypatch.setattr(redis_fake, "set", failing_set)
    response = client.get("/scooters/7")
    assert response.status_code == 200
    assert response.headers["X-Cache"] == "BYPASS"
    assert response.json()["name"] == "Hulajnoga 7"


def test_failed_invalidation_can_leave_stale_value_until_ttl(client, redis_fake):
    """Dokumentuje ograniczenie: nieudany DELETE zostawia starą kopię do końca TTL."""
    client.post("/scooters", json=SCOOTER)
    client.get("/scooters/7")  # kopia 'available' w cache

    redis_fake.down = True
    assert client.post("/scooters/7/rent").status_code == 200  # commit OK, DELETE nieudany
    redis_fake.down = False

    stale = client.get("/scooters/7")
    assert stale.headers["X-Cache"] == "HIT"
    assert stale.json()["status"] == "available"  # stara wartość z cache
    assert client.app.state.repository.get(7).status == "rented"  # prawda w bazie


def test_rejected_rent_rolls_back_and_keeps_cache(client, redis_fake):
    client.post("/scooters", json=SCOOTER)
    client.post("/scooters/7/rent")
    client.get("/scooters/7")  # kopia 'rented' w cache
    cached_before = redis_fake.values[cache_key(7)]

    response = client.post("/scooters/7/rent")  # reguła: drugi raz nie wolno
    assert response.status_code == 409
    assert response.json() == {"detail": "Scooter is not available for rental"}

    assert client.app.state.repository.get(7).status == "rented"  # baza bez zmian
    assert redis_fake.values[cache_key(7)] == cached_before  # cache nietknięty


def test_missing_scooter_is_not_cached(client, redis_fake):
    response = client.get("/scooters/404")
    assert response.status_code == 404
    assert response.json() == {"detail": "Scooter not found"}
    assert "X-Cache" not in response.headers
    assert redis_fake.values == {}


def test_corrupt_cache_entry_falls_back_to_database(client, redis_fake):
    client.post("/scooters", json=SCOOTER)
    redis_fake.values[cache_key(7)] = "not-json"

    response = client.get("/scooters/7")
    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert response.json()["name"] == "Hulajnoga 7"


def test_startup_requires_cache_prefix(make_client, monkeypatch):
    monkeypatch.delenv("CACHE_PREFIX")
    with pytest.raises(RuntimeError, match="CACHE_PREFIX"):
        with make_client():
            pass


def test_ready_reports_degraded_when_cache_is_down(client, redis_fake):
    assert client.get("/ready").json()["status"] == "ok"
    redis_fake.down = True
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "service": "Scooter Rental Service",
        "database": "up",
        "cache": "down",
    }
