"""FleetPulse: telemetry ingest for a simulated drone fleet.

Two probe endpoints with different jobs (`/healthz` is liveness, `/readyz` is
readiness), one ingest path, one rollup, and Prometheus metrics that the alert
rule and the Grafana dashboard both read.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import Settings
from .metrics import Metrics, build_metrics
from .models import DroneStatus, FleetSummary, TelemetryIn, TelemetryReading
from .store import DroneNotFound, DroneStore, StoreFull

SERVICE_NAME = "fleetpulse"


def create_app(settings: Settings | None = None, store: DroneStore | None = None) -> FastAPI:
    """Build the ASGI app. A factory, so tests get a fresh store and registry."""
    config = settings or Settings.from_env()
    metrics: Metrics = build_metrics()
    drones = store or DroneStore(
        max_drones=config.max_drones,
        history_size=config.history_size,
        low_battery_pct=config.low_battery_pct,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ready = True
        try:
            yield
        finally:
            app.state.ready = False

    app = FastAPI(
        title="FleetPulse",
        version=config.app_version,
        summary="Telemetry ingest and fleet status for a simulated drone fleet.",
        lifespan=lifespan,
    )
    app.state.settings = config
    app.state.store = drones
    app.state.metrics = metrics
    app.state.ready = False

    @app.middleware("http")
    async def instrument(request: Request, call_next):
        # scraping must not inflate the request counters it reports
        if request.url.path == "/metrics":
            return await call_next(request)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            route = getattr(request.scope.get("route"), "path", request.url.path)
            metrics.http_requests.labels(request.method, route, "500").inc()
            elapsed = time.perf_counter() - started
            metrics.http_duration.labels(request.method, route).observe(elapsed)
            raise
        route = getattr(request.scope.get("route"), "path", request.url.path)
        metrics.http_requests.labels(request.method, route, str(response.status_code)).inc()
        metrics.http_duration.labels(request.method, route).observe(time.perf_counter() - started)
        return response

    # -- operational endpoints -----------------------------------------
    @app.get("/healthz", tags=["ops"], summary="Liveness probe")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME, "version": config.app_version}

    @app.get("/readyz", tags=["ops"], summary="Readiness probe")
    def readyz(request: Request) -> dict[str, object]:
        if not request.app.state.ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="starting up"
            )
        return {
            "status": "ready",
            "drones": drones.drone_count(),
            "max_drones": drones.max_drones,
        }

    @app.get("/metrics", tags=["ops"], summary="Prometheus metrics")
    def prometheus_metrics() -> Response:
        return Response(content=generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    # -- telemetry ------------------------------------------------------
    @app.post(
        "/v1/telemetry",
        response_model=TelemetryReading,
        status_code=status.HTTP_201_CREATED,
        tags=["telemetry"],
        summary="Ingest one telemetry frame",
    )
    def ingest(frame: TelemetryIn) -> TelemetryReading:
        started = time.perf_counter()
        try:
            reading = drones.ingest(frame)
        except StoreFull as exc:  # pragma: no cover - defensive
            raise HTTPException(
                status_code=status.HTTP_507_INSUFFICIENT_STORAGE, detail=str(exc)
            ) from exc

        metrics.ingest_seconds.observe(time.perf_counter() - started)
        metrics.telemetry_total.inc()
        metrics.drones_tracked.set(drones.drone_count())
        metrics.battery_pct.labels(reading.drone_id).set(reading.battery_pct)
        if reading.low_battery:
            metrics.low_battery_total.inc()
        return reading

    @app.get(
        "/v1/drones",
        response_model=list[DroneStatus],
        tags=["fleet"],
        summary="Latest status of every drone",
    )
    def list_drones() -> list[DroneStatus]:
        return drones.statuses()

    @app.get(
        "/v1/drones/{drone_id}",
        response_model=DroneStatus,
        tags=["fleet"],
        summary="Latest status of one drone",
    )
    def get_drone(drone_id: str) -> DroneStatus:
        try:
            latest = drones.get(drone_id)
        except DroneNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown drone {drone_id}"
            ) from exc
        return DroneStatus(
            drone_id=latest.drone_id,
            battery_pct=latest.battery_pct,
            altitude_m=latest.altitude_m,
            speed_mps=latest.speed_mps,
            lat=latest.lat,
            lon=latest.lon,
            low_battery=latest.low_battery,
            last_seen=latest.recorded_at,
            readings=next(
                (item.readings for item in drones.statuses() if item.drone_id == drone_id), 1
            ),
        )

    @app.get(
        "/v1/drones/{drone_id}/history",
        response_model=list[TelemetryReading],
        tags=["fleet"],
        summary="Recent frames for one drone, oldest first",
    )
    def get_history(
        drone_id: str,
        limit: int = Query(default=20, ge=1, le=500),
    ) -> list[TelemetryReading]:
        try:
            return drones.history(drone_id, limit=limit)
        except DroneNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown drone {drone_id}"
            ) from exc

    @app.delete(
        "/v1/drones/{drone_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["fleet"],
        summary="Forget a drone (landed or decommissioned)",
    )
    def delete_drone(drone_id: str) -> Response:
        try:
            drones.delete(drone_id)
        except DroneNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown drone {drone_id}"
            ) from exc
        metrics.drones_tracked.set(drones.drone_count())
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/v1/fleet/summary",
        response_model=FleetSummary,
        tags=["fleet"],
        summary="Fleet-wide rollup",
    )
    def fleet_summary() -> FleetSummary:
        return drones.summary()

    return app


app = create_app()
