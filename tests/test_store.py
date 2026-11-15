"""Store and configuration behaviour, tested without HTTP in the way."""

from __future__ import annotations

import pytest

from fleetpulse.config import ConfigError, Settings
from fleetpulse.metrics import build_metrics
from fleetpulse.models import TelemetryIn
from fleetpulse.store import DroneNotFound, DroneStore


def make_frame(drone_id="drone-01", battery_pct=80.0) -> TelemetryIn:
    return TelemetryIn(
        drone_id=drone_id,
        battery_pct=battery_pct,
        altitude_m=100.0,
        speed_mps=10.0,
        lat=12.9,
        lon=77.5,
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_drones": 0},
        {"history_size": 0},
        {"low_battery_pct": -1},
        {"low_battery_pct": 101},
    ],
)
def test_store_rejects_impossible_limits(kwargs):
    with pytest.raises(ValueError):
        DroneStore(**kwargs)


def test_store_evicts_the_oldest_drone_when_full():
    store = DroneStore(max_drones=2)
    for drone_id in ("drone-01", "drone-02", "drone-03"):
        store.ingest(make_frame(drone_id=drone_id))
    assert [item.drone_id for item in store.statuses()] == ["drone-02", "drone-03"]


def test_history_is_bounded_by_history_size():
    store = DroneStore(history_size=3)
    for battery in range(60, 70):
        store.ingest(make_frame(battery_pct=float(battery)))
    history = store.history("drone-01", limit=100)
    assert len(history) == 3
    assert history[-1].battery_pct == 69.0


def test_unknown_drone_raises():
    store = DroneStore()
    with pytest.raises(DroneNotFound):
        store.get("ghost-01")
    with pytest.raises(DroneNotFound):
        store.history("ghost-01")
    with pytest.raises(DroneNotFound):
        store.delete("ghost-01")


def test_reset_clears_everything():
    store = DroneStore()
    store.ingest(make_frame())
    store.reset()
    assert store.drone_count() == 0
    assert store.summary().readings == 0


def test_summary_of_an_empty_store_is_zeroed():
    summary = DroneStore().summary()
    assert summary.drones == 0
    assert summary.mean_battery_pct == 0.0
    assert summary.low_battery == []


def test_low_battery_threshold_is_configurable():
    store = DroneStore(low_battery_pct=50)
    reading = store.ingest(make_frame(battery_pct=49))
    assert reading.low_battery is True
    assert store.summary().low_battery == ["drone-01"]


def test_eviction_of_an_empty_store_is_a_noop():
    store = DroneStore(max_drones=1)
    store._evict_oldest_locked()
    assert store.drone_count() == 0


# -- configuration ------------------------------------------------------
def test_settings_defaults():
    settings = Settings.from_env({})
    assert settings.low_battery_pct == 20.0
    assert settings.max_drones == 500
    assert settings.history_size == 50
    assert settings.app_version == "0.0.0-dev"
    assert settings.log_level == "info"


def test_settings_read_the_environment():
    settings = Settings.from_env(
        {
            "LOW_BATTERY_PCT": "35.5",
            "MAX_DRONES": "42",
            "HISTORY_SIZE": "7",
            "APP_VERSION": "sha-abc1234",
            "LOG_LEVEL": "DEBUG",
        }
    )
    assert settings.low_battery_pct == 35.5
    assert settings.max_drones == 42
    assert settings.history_size == 7
    assert settings.app_version == "sha-abc1234"
    assert settings.log_level == "debug"


def test_blank_values_fall_back_to_defaults():
    settings = Settings.from_env({"LOW_BATTERY_PCT": " ", "MAX_DRONES": "", "LOG_LEVEL": ""})
    assert settings.low_battery_pct == 20.0
    assert settings.max_drones == 500
    assert settings.log_level == "info"


@pytest.mark.parametrize(
    "env",
    [
        {"LOW_BATTERY_PCT": "half"},
        {"LOW_BATTERY_PCT": "101"},
        {"MAX_DRONES": "many"},
        {"MAX_DRONES": "0"},
        {"HISTORY_SIZE": "0"},
    ],
)
def test_bad_configuration_fails_fast(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


# -- metrics ------------------------------------------------------------
def test_metrics_build_on_an_isolated_registry():
    metrics = build_metrics()
    metrics.telemetry_total.inc()
    metrics.battery_pct.labels("drone-01").set(42.0)
    metrics.drones_tracked.set(1)
    assert metrics.registry.get_sample_value("fleetpulse_telemetry_total") == 1.0
    assert metrics.registry.get_sample_value("fleetpulse_drones_tracked") == 1.0
    assert (
        metrics.registry.get_sample_value("fleetpulse_drone_battery_pct", {"drone_id": "drone-01"})
        == 42.0
    )
