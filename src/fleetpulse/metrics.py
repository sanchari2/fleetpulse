"""Prometheus metrics, built per-application so tests get a clean registry.

Metric names follow the Prometheus convention: a unit suffix where one exists,
`_total` for counters. `fleetpulse_drone_battery_pct` is the series the Grafana
dashboard and the DroneLowBattery alert both key on, so it is a gauge labelled
by drone.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

INGEST_BUCKETS = (0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25)
HTTP_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)


@dataclass(frozen=True)
class Metrics:
    """Handles to every metric the service writes to."""

    registry: CollectorRegistry
    telemetry_total: Counter
    low_battery_total: Counter
    drones_tracked: Gauge
    battery_pct: Gauge
    ingest_seconds: Histogram
    http_requests: Counter
    http_duration: Histogram


def build_metrics(registry: CollectorRegistry | None = None) -> Metrics:
    """Create the metric family on its own registry."""
    reg = registry or CollectorRegistry()
    return Metrics(
        registry=reg,
        telemetry_total=Counter(
            "fleetpulse_telemetry_total",
            "Telemetry frames accepted since process start.",
            registry=reg,
        ),
        low_battery_total=Counter(
            "fleetpulse_low_battery_total",
            "Frames that arrived below the low-battery threshold.",
            registry=reg,
        ),
        drones_tracked=Gauge(
            "fleetpulse_drones_tracked",
            "Drones with at least one frame in the store.",
            registry=reg,
        ),
        battery_pct=Gauge(
            "fleetpulse_drone_battery_pct",
            "Last reported battery percentage, per drone.",
            ["drone_id"],
            registry=reg,
        ),
        ingest_seconds=Histogram(
            "fleetpulse_ingest_seconds",
            "Server-side ingest latency in seconds.",
            buckets=INGEST_BUCKETS,
            registry=reg,
        ),
        http_requests=Counter(
            "fleetpulse_http_requests_total",
            "HTTP requests served, by method, route template and status.",
            ["method", "path", "status"],
            registry=reg,
        ),
        http_duration=Histogram(
            "fleetpulse_http_request_duration_seconds",
            "HTTP request latency in seconds.",
            ["method", "path"],
            buckets=HTTP_BUCKETS,
            registry=reg,
        ),
    )
