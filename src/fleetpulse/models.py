"""Request and response models.

Every numeric field is bounded: a drone that reports nonsense (a battery at
140%, an altitude of 90km) is a bug on the aircraft, and the API should reject
it at the edge rather than let it into the dashboard.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

DRONE_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


class TelemetryIn(BaseModel):
    """One telemetry frame from one drone."""

    drone_id: Annotated[
        str,
        Field(
            min_length=3,
            max_length=32,
            pattern=DRONE_ID_PATTERN,
            description="Stable airframe identifier, lowercase, hyphen separated.",
            examples=["drone-07"],
        ),
    ]
    battery_pct: Annotated[float, Field(ge=0, le=100, description="Battery state of charge.")]
    altitude_m: Annotated[
        float, Field(ge=-5, le=5000, description="Altitude above take-off, metres.")
    ]
    speed_mps: Annotated[float, Field(ge=0, le=100, description="Ground speed, metres per second.")]
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]
    recorded_at: datetime | None = Field(
        default=None,
        description="Clock time on the aircraft. Server receive time is used when omitted.",
    )


class TelemetryReading(TelemetryIn):
    """A stored frame, with server-side bookkeeping attached."""

    recorded_at: datetime
    received_at: datetime
    sequence: int = Field(description="Monotonic ingest sequence assigned by the API.")
    low_battery: bool = Field(
        description="True when battery_pct is under the configured threshold."
    )


class DroneStatus(BaseModel):
    """Latest known state of one drone."""

    drone_id: str
    battery_pct: float
    altitude_m: float
    speed_mps: float
    lat: float
    lon: float
    low_battery: bool
    last_seen: datetime
    readings: int


class FleetSummary(BaseModel):
    """Fleet-wide rollup, the shape a dashboard or an alert rule wants."""

    drones: int
    readings: int
    low_battery: list[str]
    mean_battery_pct: float
    low_battery_threshold_pct: float
