"""Runtime configuration, read from the environment exactly once."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


class ConfigError(ValueError):
    """Raised when an environment variable is present but unusable."""


def _number(
    env: Mapping[str, str], key: str, default: float, *, minimum: float, maximum: float
) -> float:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be between {minimum} and {maximum}, got {value}")
    return value


def _integer(
    env: Mapping[str, str], key: str, default: int, *, minimum: int, maximum: int
) -> int:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be between {minimum} and {maximum}, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    """Everything the service needs to know about its environment."""

    low_battery_pct: float = 20.0
    max_drones: int = 500
    history_size: int = 50
    app_version: str = "0.0.0-dev"
    log_level: str = "info"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        return cls(
            low_battery_pct=_number(
                source, "LOW_BATTERY_PCT", 20.0, minimum=0.0, maximum=100.0
            ),
            max_drones=_integer(source, "MAX_DRONES", 500, minimum=1, maximum=100_000),
            history_size=_integer(source, "HISTORY_SIZE", 50, minimum=1, maximum=10_000),
            app_version=(source.get("APP_VERSION") or "0.0.0-dev").strip(),
            log_level=(source.get("LOG_LEVEL") or "info").strip().lower(),
        )
