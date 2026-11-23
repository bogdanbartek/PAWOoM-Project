"""Insurance Service — mikrousługa ubezpieczeń hulajnóg.

Właściciel danych: polisy ubezpieczeniowe (`id`, `scooter_id`, `rate_percent`, `status`).
Danych hulajnóg NIE przechowuje - pyta o nie SCOOTER-SERVICE przez Eurekę.

LAB5: konsumuje zdarzenia `PaymentCompleted` z RabbitMQ →
automatycznie tworzy rekordy pokrycia ubezpieczeniowego, ale tylko gdy hulajnoga
ma aktywną polisę. Składka = kwota płatności × `rate_percent` polisy / 100;
rekord wskazuje tę polisę (`insurance_id`).
"""
import logging
from contextlib import asynccontextmanager
from urllib.error import HTTPError, URLError

from fastapi import FastAPI, HTTPException, Request

from app.eureka import create_eureka_client
from app.events import (
    QUEUE_NAME,
    ROUTING_KEY,
    InvalidEventError,
    PaymentCompleted,
    parse_payment_completed,
)
from app.messaging import BrokerUnavailableError, RabbitEventBroker
from app.models import (
    CoverageRecord,
    Insurance,
    InsuranceCreate,
    InsuranceDetails,
)

SERVICE_NAME = "Insurance Service"
EUREKA_APP_NAME = "INSURANCE-SERVICE"
DEFAULT_PORT = 8103

SCOOTER_SERVICE = "SCOOTER-SERVICE"  # nazwa logiczna zależności w Eurece
DEPENDENCY_TIMEOUT_SECONDS = 3

logger = logging.getLogger(__name__)


def create_app(eureka_client=None, event_broker=None) -> FastAPI:
    """Fabryka aplikacji. Testy podają zamiennik klienta Eureka i brokera."""
    registry = eureka_client if eureka_client is not None else create_eureka_client(
        EUREKA_APP_NAME, DEFAULT_PORT
    )
    broker = event_broker if event_broker is not None else RabbitEventBroker()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Magazyn w pamięci procesu.
        app.state.insurances: dict[int, Insurance] = {}
        # LAB5: pokrycie ubezpieczeniowe z zdarzeń, klucz = payment_id.
        app.state.coverage: dict[int, CoverageRecord] = {}
        # LAB5: zbiór przetworzonych event_id (idempotentność w pamięci).
        app.state.processed_events: set[str] = set()

        app.state.eureka_client = registry
        app.state.event_broker = broker
        try:
            broker.bind_queue(QUEUE_NAME, ROUTING_KEY)
        except BrokerUnavailableError:
            logger.warning("RabbitMQ unavailable at startup; queue %s not bound yet", QUEUE_NAME)

        await registry.start()
        try:
            yield
        finally:
            try:
                await registry.stop()
            finally:
                broker.close()

    app = FastAPI(
        title=SERVICE_NAME,
        description="Student microservice for scooter rental insurance",
        version="0.1.0",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------ health

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME}

    # ------------------------------------------------------------ insurances

    @app.get("/insurances", response_model=list[Insurance])
    async def list_insurances(request: Request) -> list[Insurance]:
        return list(request.app.state.insurances.values())

    @app.get("/insurances/{insurance_id}", response_model=Insurance)
    async def get_insurance(insurance_id: int, request: Request) -> Insurance:
        return _get_or_404(request, insurance_id)

    @app.post("/insurances", response_model=Insurance, status_code=201)
    async def create_insurance(data: InsuranceCreate, request: Request) -> Insurance:
        insurances = request.app.state.insurances
        if data.id in insurances:
            raise HTTPException(status_code=409, detail="Insurance with this ID already exists")

        # Polisa powstaje tylko dla hulajnogi, której istnienie potwierdziła usługa floty.
        await _fetch_scooter(request, data.scooter_id)

        insurance = Insurance(**data.model_dump())
        insurances[insurance.id] = insurance
        return insurance

    @app.post("/insurances/{insurance_id}/cancel", response_model=Insurance)
    async def cancel_insurance(insurance_id: int, request: Request) -> Insurance:
        insurance = _get_or_404(request, insurance_id)
        if insurance.status == "cancelled":
            raise HTTPException(status_code=409, detail="Insurance is already cancelled")
        updated = insurance.model_copy(update={"status": "cancelled"})
        request.app.state.insurances[insurance_id] = updated
        return updated

    @app.get("/insurances/{insurance_id}/details", response_model=InsuranceDetails)
    async def insurance_details(insurance_id: int, request: Request) -> InsuranceDetails:
        insurance = _get_or_404(request, insurance_id)
        scooter = await _fetch_scooter(request, insurance.scooter_id)
        return InsuranceDetails(insurance=insurance, scooter=scooter)

    # ---------------------------------------------------------------- coverage (LAB5)

    @app.get("/coverage", response_model=list[CoverageRecord])
    async def list_coverage(request: Request) -> list[CoverageRecord]:
        """LAB5: lista rekordów pokrycia ubezpieczeniowego z zdarzeń PaymentCompleted."""
        return list(request.app.state.coverage.values())

    @app.post("/insurances/payment-events/consume")
    def consume_payment_events(request: Request) -> dict:
        """LAB5: pobiera dostępne wiadomości z kolejki i tworzy rekordy pokrycia."""
        stats = {"applied": 0, "duplicates": 0, "ignored": 0, "uninsured": 0}

        def handle_event(event: dict) -> None:
            parsed: PaymentCompleted | None = parse_payment_completed(event)
            if parsed is None:
                stats["ignored"] += 1
                return
            if parsed.event_id in request.app.state.processed_events:
                stats["duplicates"] += 1
                return
            # Pokrycie należy się tylko hulajnodze z aktywną polisą (stan w chwili odbioru zdarzenia).
            policy = _active_policy_for(request, parsed.scooter_id)
            if policy is None:
                # Zdarzenie przetworzone (ACK), ale bez pokrycia - płatność nie była ubezpieczona.
                request.app.state.processed_events.add(parsed.event_id)
                stats["uninsured"] += 1
                return
            # Idempotentny zapis: każde payment_id tworzy dokładnie jeden rekord pokrycia.
            if parsed.payment_id not in request.app.state.coverage:
                premium = round(parsed.amount * policy.rate_percent / 100, 2)
                request.app.state.coverage[parsed.payment_id] = CoverageRecord(
                    insurance_id=policy.id,
                    scooter_id=parsed.scooter_id,
                    payment_id=parsed.payment_id,
                    rate_percent=policy.rate_percent,
                    premium=premium,
                )
            request.app.state.processed_events.add(parsed.event_id)
            stats["applied"] += 1

        try:
            consumed = request.app.state.event_broker.consume_available(QUEUE_NAME, handle_event)
        except BrokerUnavailableError as exc:
            raise HTTPException(status_code=503, detail="RabbitMQ broker is unavailable") from exc
        except (ValueError, LookupError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid event payload: {exc}") from exc

        return {
            "queue": QUEUE_NAME,
            "consumed_messages": consumed,
            "applied_events": stats["applied"],
            "duplicate_events": stats["duplicates"],
            "ignored_events": stats["ignored"],
            "uninsured_events": stats["uninsured"],
            "total_coverage_records": len(request.app.state.coverage),
        }

    return app


def _get_or_404(request: Request, insurance_id: int) -> Insurance:
    insurance = request.app.state.insurances.get(insurance_id)
    if insurance is None:
        raise HTTPException(status_code=404, detail="Insurance not found")
    return insurance


def _active_policy_for(request: Request, scooter_id: int) -> Insurance | None:
    """Aktywna polisa hulajnogi; przy kilku wybieramy najstarszą (najmniejsze id)."""
    active = [
        insurance
        for insurance in request.app.state.insurances.values()
        if insurance.scooter_id == scooter_id and insurance.status == "active"
    ]
    return min(active, key=lambda insurance: insurance.id, default=None)


async def _fetch_scooter(request: Request, scooter_id: int) -> dict:
    """GET /scooters/{id} w SCOOTER-SERVICE, adres wybiera klient Eureka po nazwie logicznej."""
    try:
        scooter = await request.app.state.eureka_client.do_service(
            SCOOTER_SERVICE,
            f"/scooters/{scooter_id}",
            return_type="json",
            timeout=DEPENDENCY_TIMEOUT_SECONDS,
        )
    except HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(status_code=404, detail="Scooter not found") from exc
        raise HTTPException(
            status_code=502, detail="Scooter Service returned an HTTP error"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="Scooter Service is unavailable") from exc

    if not isinstance(scooter, dict) or scooter.get("id") != scooter_id:
        raise HTTPException(status_code=502, detail="Scooter Service returned an invalid response")
    return scooter


app = create_app()
