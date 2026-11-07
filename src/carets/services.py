"""Caller-owned configuration, services and diagnostics outside rendered output."""

from dataclasses import dataclass, field
import json
from pathlib import Path


def load_config(path, *, max_bytes=1_048_576):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate configuration key")
            result[key] = value
        return result
    def constant(_value):
        raise ValueError("Configuration numbers must be finite")
    with Path(path).open("rb") as stream:
        payload = stream.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError("Configuration exceeds its byte limit")
    value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    if type(value) is not dict:
        raise ValueError("Configuration must be an object")
    # Re-encoding also rejects overflowing numeric literals such as 1e999.
    json.dumps(value, allow_nan=False).encode("utf-8")
    return value


def _redact(value):
    if isinstance(value, dict):
        return {key: "[redacted]" if any(word in key.lower() for word in ("password", "secret", "token", "api_key")) else _redact(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


@dataclass
class ApplicationContext:
    config: dict = field(default_factory=dict)
    services: dict = field(default_factory=dict)
    logger: object = None

    def log(self, event, **fields):
        if self.logger is not None:
            self.logger.info(event, extra={"event": event, "fields": _redact(fields)})

    def report_crash(self, error, stream):
        """A safe type-only diagnostic on an explicitly selected external stream."""
        stream.write(f"Application failed ({type(error).__name__})\n")
        stream.flush()
        self.log("application_failure", error_type=type(error).__name__)
