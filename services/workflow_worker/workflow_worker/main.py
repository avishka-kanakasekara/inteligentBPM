"""Entrypoint for the native workflow worker process."""

from __future__ import annotations

import logging
import sys

import structlog

from workflow_worker.runner import run_worker
from workflow_worker.settings import WorkerSettings


def configure_logging(level: str) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def main() -> None:
    settings = WorkerSettings()
    configure_logging(settings.log_level)
    run_worker(settings)


if __name__ == "__main__":
    main()
