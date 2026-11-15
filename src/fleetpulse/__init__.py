"""FleetPulse: telemetry service for a simulated drone fleet."""

__version__ = "0.1.0"

__all__ = ["__version__", "create_app", "Settings", "DroneStore"]


def __getattr__(name: str):
    # Imported lazily so `import fleetpulse` stays cheap and dependency-free.
    if name == "create_app":
        from .main import create_app

        return create_app
    if name == "Settings":
        from .config import Settings

        return Settings
    if name == "DroneStore":
        from .store import DroneStore

        return DroneStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
