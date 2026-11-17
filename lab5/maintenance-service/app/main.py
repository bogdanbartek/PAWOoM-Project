"""Maintenance Service — mikrousługa serwisowania hulajnóg.

Właściciel danych: zlecenia serwisowe (`id`, `scooter_id`, `description`, `status`).
Danych hulajnóg NIE przechowuje - pyta o nie SCOOTER-SERVICE przez Eurekę.

Maszyna stanów zlecenia:
  pending  →  in_progress  →  completed
"""
from contextlib import asynccontextmanager
from urllib.error import HTTPError, URLError

from fastapi import FastAPI, HTTPException, Request

from app.eureka import create_eureka_client
from app.models import MaintenanceCreate, MaintenanceDetails, MaintenanceJob

SERVICE_NAME = "Maintenance Service"
EUREKA_APP_NAME = "MAINTENANCE-SERVICE"
DEFAULT_PORT = 8104

SCOOTER_SERVICE = "SCOOTER-SERVICE"
DEPENDENCY_TIMEOUT_SECONDS = 3


def create_app(eureka_client=None) -> FastAPI:
    """Fabryka aplikacji. Testy podają zamiennik klienta Eureka."""
    registry = eureka_client if eureka_client is not None else create_eureka_client(
        EUREKA_APP_NAME, DEFAULT_PORT
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.jobs: dict[int, MaintenanceJob] = {}
        app.state.eureka_client = registry
        await registry.start()
        try:
            yield
        finally:
            await registry.stop()

    app = FastAPI(
        title=SERVICE_NAME,
        description="Student microservice for scooter maintenance management",
        version="0.1.0",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------ health

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME}

    # -------------------------------------------------------------------- jobs

    @app.get("/jobs", response_model=list[MaintenanceJob])
    async def list_jobs(request: Request) -> list[MaintenanceJob]:
        return list(request.app.state.jobs.values())

    @app.get("/jobs/{job_id}", response_model=MaintenanceJob)
    async def get_job(job_id: int, request: Request) -> MaintenanceJob:
        return _get_or_404(request, job_id)

    @app.post("/jobs", response_model=MaintenanceJob, status_code=201)
    async def create_job(data: MaintenanceCreate, request: Request) -> MaintenanceJob:
        jobs = request.app.state.jobs
        if data.id in jobs:
            raise HTTPException(status_code=409, detail="Job with this ID already exists")

        # Zlecenie powstaje tylko dla hulajnogi, której istnienie potwierdziła usługa floty.
        await _fetch_scooter(request, data.scooter_id)

        job = MaintenanceJob(**data.model_dump())
        jobs[job.id] = job
        return job

    @app.post("/jobs/{job_id}/start", response_model=MaintenanceJob)
    async def start_job(job_id: int, request: Request) -> MaintenanceJob:
        """Reguła: można rozpocząć tylko zlecenie w stanie `pending`."""
        job = _get_or_404(request, job_id)
        if job.status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Job cannot be started from status '{job.status}' (must be 'pending')",
            )
        updated = job.model_copy(update={"status": "in_progress"})
        request.app.state.jobs[job_id] = updated
        return updated

    @app.post("/jobs/{job_id}/complete", response_model=MaintenanceJob)
    async def complete_job(job_id: int, request: Request) -> MaintenanceJob:
        """Reguła: można zakończyć tylko zlecenie w stanie `in_progress`."""
        job = _get_or_404(request, job_id)
        if job.status != "in_progress":
            raise HTTPException(
                status_code=409,
                detail=f"Job cannot be completed from status '{job.status}' (must be 'in_progress')",
            )
        updated = job.model_copy(update={"status": "completed"})
        request.app.state.jobs[job_id] = updated
        return updated

    @app.get("/jobs/{job_id}/details", response_model=MaintenanceDetails)
    async def job_details(job_id: int, request: Request) -> MaintenanceDetails:
        job = _get_or_404(request, job_id)
        scooter = await _fetch_scooter(request, job.scooter_id)
        return MaintenanceDetails(job=job, scooter=scooter)

    return app


def _get_or_404(request: Request, job_id: int) -> MaintenanceJob:
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Maintenance job not found")
    return job


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
