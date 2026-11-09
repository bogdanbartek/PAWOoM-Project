import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.cache import JsonCache, make_redis
from app.database import Base, make_database
from app.db_models import ScooterRow  # noqa: F401 - rejestruje tabelę w Base.metadata
from app.eureka import create_eureka_client
from app.models import Scooter, ScooterCreate
from app.repository import (
    DuplicateScooterError,
    ScooterNotFoundError,
    ScooterRepository,
    ScooterStateError,
)

SERVICE_NAME = "Scooter Rental Service"
DEFAULT_DATABASE_URL = "sqlite:///./app.db"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_CACHE_TTL_SECONDS = 60
EUREKA_APP_NAME = "SCOOTER-SERVICE"  # nazwa logiczna w Eurece (LAB3)
DEFAULT_PORT = 8101

logger = logging.getLogger(__name__)


def create_app(database_url: str | None = None, redis_client=None, eureka_client=None) -> FastAPI:
    """Fabryka aplikacji.

    Parametry pozwalają testom podać bazę w `tmp_path`, zamiennik Redis
    i zamiennik klienta Eureka. Bez parametrów konfiguracja pochodzi ze
    zmiennych środowiskowych.
    """
    registry = eureka_client if eureka_client is not None else create_eureka_client(
        EUREKA_APP_NAME, DEFAULT_PORT
    )

    @asynccontextmanager
    async def storage_lifespan(app: FastAPI):
        # CACHE_PREFIX musi być ustawiony przed startem - bez niego nie wiadomo,
        # do kogo należą klucze na (potencjalnie wspólnym) serwerze Redis.
        prefix = os.environ.get("CACHE_PREFIX")
        if not prefix:
            raise RuntimeError("CACHE_PREFIX environment variable must be set before start")
        ttl = int(os.getenv("CACHE_TTL_SECONDS", str(DEFAULT_CACHE_TTL_SECONDS)))

        url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
        engine, sessions = make_database(url)
        # create_all tworzy brakujące tabele, nie kasuje danych i nie migruje kolumn.
        Base.metadata.create_all(engine)

        client = redis_client if redis_client is not None else make_redis(
            os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
        )

        app.state.engine = engine
        app.state.redis = client
        app.state.repository = ScooterRepository(sessions)
        app.state.cache = JsonCache(client, prefix=prefix, ttl=ttl, resource_name="scooter")
        try:
            yield
        finally:
            client.close()
            engine.dispose()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Kolejność: zasoby LAB2 -> start klienta Eureka -> żądania
        # -> stop klienta (wyrejestrowanie) -> zamknięcie zasobów LAB2.
        async with storage_lifespan(app):
            app.state.eureka_client = registry
            await registry.start()
            try:
                yield
            finally:
                await registry.stop()

    app = FastAPI(
        title=SERVICE_NAME,
        description="Student microservice for scooter rentals",
        version="0.3.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME}

    @app.get("/ready")
    def ready(request: Request):
        """Rozszerzenie LAB2: gotowość zależności (baza wymagana, cache opcjonalny)."""
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "service": SERVICE_NAME, "database": "down", "cache": "unknown"},
            )
        try:
            request.app.state.redis.ping()
            cache_state = "up"
        except RedisError:
            cache_state = "down"
        return {
            "status": "ok" if cache_state == "up" else "degraded",
            "service": SERVICE_NAME,
            "database": "up",
            "cache": cache_state,
        }

    @app.get("/scooters", response_model=list[Scooter])
    def list_scooters(request: Request) -> list[Scooter]:
        return request.app.state.repository.list_all()

    @app.get("/scooters/{scooter_id}", response_model=Scooter)
    def get_scooter(scooter_id: int, request: Request, response: Response) -> Scooter:
        """Cache-aside: najpierw Redis, przy MISS baza i zapis kopii z TTL."""
        cache: JsonCache = request.app.state.cache
        cached, source = cache.get(scooter_id)
        if cached is not None:
            response.headers["X-Cache"] = source  # HIT
            return Scooter.model_validate(cached)

        try:
            scooter = request.app.state.repository.get(scooter_id)
        except ScooterNotFoundError:
            # Odpowiedzi 404 nie zapisujemy w cache.
            raise HTTPException(status_code=404, detail="Scooter not found")

        if source != "BYPASS" and not cache.put(scooter_id, scooter.model_dump(mode="json")):
            source = "BYPASS"  # Redis padł między GET a SET
        response.headers["X-Cache"] = source
        return scooter

    @app.post("/scooters", response_model=Scooter, status_code=201)
    def create_scooter(data: ScooterCreate, request: Request) -> Scooter:
        try:
            return request.app.state.repository.create(data)
        except DuplicateScooterError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/scooters/{scooter_id}/rent", response_model=Scooter)
    def rent_scooter(scooter_id: int, request: Request) -> Scooter:
        return _change_status(request, scooter_id, request.app.state.repository.rent)

    @app.post("/scooters/{scooter_id}/return", response_model=Scooter)
    def return_scooter(scooter_id: int, request: Request) -> Scooter:
        return _change_status(request, scooter_id, request.app.state.repository.return_scooter)

    return app


def _change_status(request: Request, scooter_id: int, operation) -> Scooter:
    try:
        scooter = operation(scooter_id)  # commit w bazie
    except ScooterNotFoundError:
        raise HTTPException(status_code=404, detail="Scooter not found")
    except ScooterStateError as exc:
        # Reguła odrzuciła operację: transakcja wycofana, cache nietknięty.
        raise HTTPException(status_code=409, detail=str(exc))

    # Dopiero PO commicie unieważniamy kopię w cache. Błąd Redis nie cofa zapisu
    # w bazie - stara wartość może wtedy przetrwać najdłużej do końca TTL.
    if not request.app.state.cache.delete(scooter_id):
        logger.warning("Cache invalidation failed for scooter %s", scooter_id)
    return scooter


app = create_app()
