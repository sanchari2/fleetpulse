"""Generate believable drone telemetry against a running FleetPulse API.

Batteries drain over time, so the DroneLowBattery alert fires a minute or two
after `docker compose up` — which is the point of shipping a simulator instead
of a curl script.

    API_URL=http://localhost:8000 DRONES=6 python simulator/simulate.py
"""

from __future__ import annotations

import math
import os
import random
import signal
import sys
import time

import requests

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
DRONES = int(os.getenv("DRONES", "6"))
INTERVAL_S = float(os.getenv("INTERVAL_S", "2"))
START_BATTERY = float(os.getenv("START_BATTERY", "95"))
DRAIN_PER_FRAME = float(os.getenv("DRAIN_PER_FRAME", "0.7"))
BATTERY_FLOOR = float(os.getenv("BATTERY_FLOOR", "6"))
STARTUP_GRACE_S = float(os.getenv("STARTUP_GRACE_S", "60"))

# a loose circuit over a field near Bengaluru
HOME_LAT, HOME_LON = 12.9716, 77.5946

RUNNING = True


def _stop(signum, _frame):
    global RUNNING
    print(f"simulator: signal {signum}, stopping after this frame", flush=True)
    RUNNING = False


class Drone:
    """One airframe with its own position, battery and heading."""

    def __init__(self, index: int) -> None:
        self.drone_id = f"drone-{index:02d}"
        self.battery = max(BATTERY_FLOOR, START_BATTERY - random.uniform(0, 15))
        self.heading = random.uniform(0, 2 * math.pi)
        self.radius = random.uniform(0.0008, 0.0025)
        self.lat = HOME_LAT + random.uniform(-0.01, 0.01)
        self.lon = HOME_LON + random.uniform(-0.01, 0.01)
        self.altitude = random.uniform(80, 150)
        self.speed = random.uniform(8, 18)

    def step(self) -> dict:
        self.heading += random.uniform(-0.25, 0.25)
        self.lat += self.radius * math.cos(self.heading)
        self.lon += self.radius * math.sin(self.heading)
        self.altitude = max(30.0, min(400.0, self.altitude + random.uniform(-4, 4)))
        self.speed = max(0.0, min(30.0, self.speed + random.uniform(-1.5, 1.5)))
        self.battery = max(BATTERY_FLOOR, self.battery - DRAIN_PER_FRAME * random.uniform(0.7, 1.3))
        return {
            "drone_id": self.drone_id,
            "battery_pct": round(self.battery, 2),
            "altitude_m": round(self.altitude, 1),
            "speed_mps": round(self.speed, 2),
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
        }


def wait_for_api(session: requests.Session) -> bool:
    """Give the API a chance to come up; compose healthchecks usually win."""
    deadline = time.monotonic() + STARTUP_GRACE_S
    while time.monotonic() < deadline and RUNNING:
        try:
            if session.get(f"{API_URL}/healthz", timeout=3).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    fleet = [Drone(index) for index in range(1, DRONES + 1)]
    session = requests.Session()

    if not wait_for_api(session):
        print(f"simulator: {API_URL} never became healthy, giving up", file=sys.stderr)
        return 1

    print(f"simulator: {len(fleet)} drones -> {API_URL} every {INTERVAL_S}s", flush=True)
    frames = 0
    while RUNNING:
        for drone in fleet:
            payload = drone.step()
            try:
                response = session.post(f"{API_URL}/v1/telemetry", json=payload, timeout=5)
                if response.status_code >= 400:
                    detail = response.text[:200]
                    print(f"simulator: {drone.drone_id} rejected: {detail}", flush=True)
            except requests.RequestException as exc:
                print(f"simulator: {drone.drone_id} failed: {exc}", flush=True)
        frames += 1

        if frames % 10 == 0:
            try:
                summary = session.get(f"{API_URL}/v1/fleet/summary", timeout=5).json()
                print(
                    f"simulator: frames={frames} drones={summary.get('drones')} "
                    f"mean_battery={summary.get('mean_battery_pct')}% "
                    f"low={summary.get('low_battery')}",
                    flush=True,
                )
            except (requests.RequestException, ValueError) as exc:
                print(f"simulator: summary failed: {exc}", flush=True)

        time.sleep(INTERVAL_S)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
