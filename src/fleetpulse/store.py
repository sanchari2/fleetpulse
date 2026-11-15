"""In-memory telemetry store.

A real fleet would land frames in TimescaleDB or Timestream. For this project
the store is deliberately small and honest about its limits: bounded by drone
count, bounded history per drone, oldest-first eviction. That way the service
degrades under pressure instead of being OOM-killed, which is the failure mode
worth demonstrating.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .models import DroneStatus, FleetSummary, TelemetryIn, TelemetryReading


class DroneNotFound(KeyError):
    """Raised when a drone id has never been seen."""


class StoreFull(RuntimeError):
    """Raised when the store cannot make room for another drone."""


@dataclass
class _DroneState:
    latest: TelemetryReading
    readings: int = 1
    history: deque[TelemetryReading] = field(default_factory=deque)


class DroneStore:
    """Thread-safe, bounded store of the latest frame plus recent history."""

    def __init__(
        self,
        *,
        max_drones: int = 500,
        history_size: int = 50,
        low_battery_pct: float = 20.0,
    ) -> None:
        if max_drones < 1:
            raise ValueError("max_drones must be >= 1")
        if history_size < 1:
            raise ValueError("history_size must be >= 1")
        if not 0 <= low_battery_pct <= 100:
            raise ValueError("low_battery_pct must be between 0 and 100")
        self._lock = threading.Lock()
        self._drones: dict[str, _DroneState] = {}
        self._sequence = 0
        self._total_readings = 0
        self.max_drones = max_drones
        self.history_size = history_size
        self.low_battery_pct = low_battery_pct

    # -- writes ---------------------------------------------------------
    def ingest(self, frame: TelemetryIn) -> TelemetryReading:
        """Store one frame and return it with server-side fields filled in."""
        now = datetime.now(UTC)
        with self._lock:
            state = self._drones.get(frame.drone_id)
            if state is None and len(self._drones) >= self.max_drones:
                self._evict_oldest_locked()
                if len(self._drones) >= self.max_drones:
                    raise StoreFull(
                        f"store is full ({self.max_drones} drones) and nothing is evictable"
                    )

            self._sequence += 1
            self._total_readings += 1
            reading = TelemetryReading(
                drone_id=frame.drone_id,
                battery_pct=frame.battery_pct,
                altitude_m=frame.altitude_m,
                speed_mps=frame.speed_mps,
                lat=frame.lat,
                lon=frame.lon,
                recorded_at=frame.recorded_at or now,
                received_at=now,
                sequence=self._sequence,
                low_battery=frame.battery_pct < self.low_battery_pct,
            )

            if state is None:
                state = _DroneState(latest=reading, history=deque(maxlen=self.history_size))
                self._drones[frame.drone_id] = state
            else:
                state.latest = reading
                state.readings += 1
            state.history.append(reading)
            return reading

    def delete(self, drone_id: str) -> None:
        with self._lock:
            if drone_id not in self._drones:
                raise DroneNotFound(drone_id)
            del self._drones[drone_id]

    def reset(self) -> None:
        """Drop all state. Used by tests and by the demo reset hook."""
        with self._lock:
            self._drones.clear()
            self._sequence = 0
            self._total_readings = 0

    # -- reads ----------------------------------------------------------
    def get(self, drone_id: str) -> TelemetryReading:
        with self._lock:
            state = self._drones.get(drone_id)
            if state is None:
                raise DroneNotFound(drone_id)
            return state.latest

    def history(self, drone_id: str, limit: int = 20) -> list[TelemetryReading]:
        with self._lock:
            state = self._drones.get(drone_id)
            if state is None:
                raise DroneNotFound(drone_id)
            frames = list(state.history)
        return frames[-limit:]

    def drone_count(self) -> int:
        with self._lock:
            return len(self._drones)

    def statuses(self) -> list[DroneStatus]:
        with self._lock:
            states = list(self._drones.items())

        result = [
            DroneStatus(
                drone_id=drone_id,
                battery_pct=state.latest.battery_pct,
                altitude_m=state.latest.altitude_m,
                speed_mps=state.latest.speed_mps,
                lat=state.latest.lat,
                lon=state.latest.lon,
                low_battery=state.latest.low_battery,
                last_seen=state.latest.recorded_at,
                readings=state.readings,
            )
            for drone_id, state in states
        ]
        result.sort(key=lambda item: item.drone_id)
        return result

    def summary(self) -> FleetSummary:
        statuses = self.statuses()
        with self._lock:
            total_readings = self._total_readings
        mean_battery = 0.0
        if statuses:
            mean_battery = round(sum(item.battery_pct for item in statuses) / len(statuses), 2)
        return FleetSummary(
            drones=len(statuses),
            readings=total_readings,
            low_battery=sorted(item.drone_id for item in statuses if item.low_battery),
            mean_battery_pct=mean_battery,
            low_battery_threshold_pct=self.low_battery_pct,
        )

    # -- internals ------------------------------------------------------
    def _evict_oldest_locked(self) -> None:
        if not self._drones:
            return
        oldest = min(self._drones, key=lambda key: self._drones[key].latest.received_at)
        del self._drones[oldest]
