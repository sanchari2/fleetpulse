"""API behaviour: probes, ingest, validation, fleet views, metrics."""

from __future__ import annotations

import pytest


def test_healthz_reports_version(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "fleetpulse", "version": "test"}


def test_readyz_reports_store_capacity(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "drones": 0, "max_drones": 100}


def test_readyz_is_503_before_startup():
    from fastapi.testclient import TestClient

    from fleetpulse.main import create_app

    app = create_app()
    # no context manager: lifespan startup never runs
    raw = TestClient(app)
    assert raw.get("/readyz").status_code == 503


def test_ingest_returns_201_with_server_fields(client, frame):
    response = client.post("/v1/telemetry", json=frame())
    assert response.status_code == 201
    body = response.json()
    assert body["drone_id"] == "drone-01"
    assert body["sequence"] == 1
    assert body["low_battery"] is False
    assert body["received_at"] is not None


def test_ingest_flags_low_battery(client, frame):
    body = client.post("/v1/telemetry", json=frame(battery_pct=9.5)).json()
    assert body["low_battery"] is True


def test_ingest_keeps_latest_state_and_a_count(client, frame):
    client.post("/v1/telemetry", json=frame(battery_pct=90))
    client.post("/v1/telemetry", json=frame(battery_pct=70))
    body = client.get("/v1/drones/drone-01").json()
    assert body["battery_pct"] == 70
    assert body["readings"] == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"drone_id": "Drone One"},
        {"drone_id": "a"},
        {"battery_pct": 140},
        {"battery_pct": -1},
        {"altitude_m": 9000},
        {"speed_mps": 400},
        {"lat": 91},
        {"lon": -181},
        {"drone_id": "drone_01"},  # underscores are not allowed
    ],
)
def test_invalid_frames_are_rejected(client, frame, payload):
    assert client.post("/v1/telemetry", json=frame(**payload)).status_code == 422


def test_incomplete_frames_are_rejected(client):
    assert client.post("/v1/telemetry", json={"drone_id": "drone-01", "battery_pct": 50}).status_code == 422


def test_unknown_drone_is_404(client):
    assert client.get("/v1/drones/ghost-01").status_code == 404
    assert client.get("/v1/drones/ghost-01/history").status_code == 404
    assert client.delete("/v1/drones/ghost-01").status_code == 404


def test_list_drones_is_sorted_by_id(client, frame):
    client.post("/v1/telemetry", json=frame(drone_id="drone-09"))
    client.post("/v1/telemetry", json=frame(drone_id="drone-02"))
    ids = [item["drone_id"] for item in client.get("/v1/drones").json()]
    assert ids == ["drone-02", "drone-09"]


def test_history_is_oldest_first_and_limit_bounded(client, frame):
    for battery in (90, 80, 70, 60):
        client.post("/v1/telemetry", json=frame(battery_pct=battery))
    history = client.get("/v1/drones/drone-01/history", params={"limit": 2}).json()
    assert [item["battery_pct"] for item in history] == [70, 60]


@pytest.mark.parametrize("limit", [0, 501, "many"])
def test_history_rejects_bad_limits(client, frame, limit):
    client.post("/v1/telemetry", json=frame())
    response = client.get("/v1/drones/drone-01/history", params={"limit": limit})
    assert response.status_code == 422


def test_delete_forgets_the_drone(client, frame):
    client.post("/v1/telemetry", json=frame())
    assert client.delete("/v1/drones/drone-01").status_code == 204
    assert client.get("/v1/drones/drone-01").status_code == 404


def test_fleet_summary_rolls_up(client, frame):
    client.post("/v1/telemetry", json=frame(drone_id="drone-01", battery_pct=80))
    client.post("/v1/telemetry", json=frame(drone_id="drone-02", battery_pct=10))
    body = client.get("/v1/fleet/summary").json()
    assert body["drones"] == 2
    assert body["readings"] == 2
    assert body["low_battery"] == ["drone-02"]
    assert body["mean_battery_pct"] == 45.0
    assert body["low_battery_threshold_pct"] == 20.0


def test_metrics_expose_the_series_the_alert_rule_needs(client, frame):
    client.post("/v1/telemetry", json=frame(battery_pct=90))
    client.post("/v1/telemetry", json=frame(drone_id="drone-02", battery_pct=5))
    text = client.get("/metrics").text
    assert 'fleetpulse_drone_battery_pct{drone_id="drone-02"} 5.0' in text
    assert "fleetpulse_telemetry_total 2.0" in text
    assert "fleetpulse_low_battery_total 1.0" in text
    assert "fleetpulse_drones_tracked 2.0" in text
    assert "fleetpulse_ingest_seconds_bucket" in text
    assert 'fleetpulse_http_requests_total{method="POST",path="/v1/telemetry",status="201"} 2.0' in text


def test_metrics_endpoint_does_not_instrument_itself(client):
    client.get("/metrics")
    assert 'path="/metrics"' not in client.get("/metrics").text


def test_openapi_schema_is_served(client):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "FleetPulse"
    assert "/v1/telemetry" in schema["paths"]


def test_package_exports_are_lazy():
    import fleetpulse

    assert fleetpulse.__version__ == "0.1.0"
    assert callable(fleetpulse.create_app)
    assert fleetpulse.Settings is not None
    assert fleetpulse.DroneStore is not None
    with pytest.raises(AttributeError):
        _ = fleetpulse.does_not_exist
