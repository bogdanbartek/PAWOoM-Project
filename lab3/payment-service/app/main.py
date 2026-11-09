"""Payment Service (LAB3) - druga usługa systemu wypożyczalni hulajnóg.

Właściciel danych: płatności (`id`, `scooter_id`, `amount`, `status`).
Danych hulajnóg NIE przechowuje - pyta o nie SCOOTER-SERVICE przez Eurekę.
"""
from contextlib import asynccontextmanager
from urllib.error import HTTPError, URLError

from fastapi import FastAPI, HTTPException, Request

from app.eureka import create_eureka_client
from app.models import Payment, PaymentCreate, PaymentDetails

SERVICE_NAME = "Payment Service"
EUREKA_APP_NAME = "PAYMENT-SERVICE"
DEFAULT_PORT = 8102

SCOOTER_SERVICE = "SCOOTER-SERVICE"  # nazwa logiczna zależności w Eurece
DEPENDENCY_TIMEOUT_SECONDS = 3


def create_app(eureka_client=None) -> FastAPI:
    """Fabryka aplikacji. Testy podają zamiennik klienta Eureka."""
    registry = eureka_client if eureka_client is not None else create_eureka_client(
        EUREKA_APP_NAME, DEFAULT_PORT
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Magazyn w pamięci procesu: na LAB3 wystarczający, trwałość dojdzie później.
        app.state.payments = {}
        app.state.eureka_client = registry
        await registry.start()
        try:
            yield
        finally:
            await registry.stop()

    app = FastAPI(
        title=SERVICE_NAME,
        description="Student microservice for scooter rental payments",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME}

    @app.get("/payments", response_model=list[Payment])
    async def list_payments(request: Request) -> list[Payment]:
        return list(request.app.state.payments.values())

    @app.get("/payments/{payment_id}", response_model=Payment)
    async def get_payment(payment_id: int, request: Request) -> Payment:
        return _get_or_404(request, payment_id)

    @app.post("/payments", response_model=Payment, status_code=201)
    async def create_payment(data: PaymentCreate, request: Request) -> Payment:
        payments = request.app.state.payments
        if data.id in payments:
            raise HTTPException(status_code=409, detail="Payment with this ID already exists")

        # Płatność powstaje tylko dla hulajnogi, której istnienie potwierdziła usługa floty.
        await _fetch_scooter(request, data.scooter_id)

        payment = Payment(**data.model_dump(), status="pending")
        payments[payment.id] = payment
        return payment

    @app.post("/payments/{payment_id}/pay", response_model=Payment)
    async def pay(payment_id: int, request: Request) -> Payment:
        payment = _get_or_404(request, payment_id)
        if payment.status != "pending":
            raise HTTPException(status_code=409, detail="Payment is already paid")
        paid = payment.model_copy(update={"status": "paid"})
        request.app.state.payments[payment_id] = paid
        return paid

    @app.get("/payments/{payment_id}/details", response_model=PaymentDetails)
    async def payment_details(payment_id: int, request: Request) -> PaymentDetails:
        payment = _get_or_404(request, payment_id)
        scooter = await _fetch_scooter(request, payment.scooter_id)
        return PaymentDetails(payment=payment, scooter=scooter)

    return app


def _get_or_404(request: Request, payment_id: int) -> Payment:
    payment = request.app.state.payments.get(payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


async def _fetch_scooter(request: Request, scooter_id: int) -> dict:
    """GET /scooters/{id} w SCOOTER-SERVICE, adres wybiera klient Eureka po nazwie logicznej.

    HTTPError musi być łapany przed URLError (jest jego podklasą).
    """
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

    # Odpowiedź niezgodna z kontraktem (np. nie JSON-obiekt hulajnogi) to też błąd zależności.
    if not isinstance(scooter, dict) or scooter.get("id") != scooter_id:
        raise HTTPException(status_code=502, detail="Scooter Service returned an invalid response")
    return scooter


app = create_app()
