"""Shared contracts for the intelligent BPM platform."""

from bpm_contracts.errors import ErrorBody, ErrorResponse
from bpm_contracts.health import HealthResponse, ReadinessCheck, ReadinessResponse

__all__ = [
    "ErrorBody",
    "ErrorResponse",
    "HealthResponse",
    "ReadinessCheck",
    "ReadinessResponse",
]

__version__ = "0.1.0"
