"""Shared fixtures."""

from __future__ import annotations

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from fleetpulse.config import Settings
from fleetpulse.main import create_app
from fleetpulse.store import DroneStore


@pytest.fixture
def settings() -> Settings:
    return Settings(low_battery_pct=20.0, max_drones=100, history_size=10, app_version="test")


@pytest.fixture
def store(settings: Settings) -> DroneStore:
    return DroneStore(
        max_drones=settings.max_drones,
        history_size=settings.history_size,
        low_battery_pct=settings.low_battery_pct,
    )


@pytest.fixture
def client(settings: Settings, store: DroneStore) -> TestClient:
    with TestClient(create_app(settings=settings, store=store)) as test_client:
        yield test_client


@pytest.fixture
def frame() -> Callable[..., dict[str, Any]]:
    """Build a valid telemetry payload, with per-test overrides."""

    def _frame(**overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "drone_id": "drone-01",
            "battery_pct": 88.0,
            "altitude_m": 120.0,
            "speed_mps": 14.5,
            "lat": 12.9716,
            "lon": 77.5946,
        }
        payload.update(overrides)
        return payload

    return _frame
