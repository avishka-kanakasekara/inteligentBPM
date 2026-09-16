"""Mock and Temporal Cloud worker runners (native processes only — no Docker)."""

from __future__ import annotations

import signal
import time
from types import FrameType

import structlog

from workflow_worker.settings import WorkerSettings

logger = structlog.get_logger("bpm.worker")


class MockWorkflowRunner:
    """
    In-process mock runner for local development without Temporal credentials.

    Periodically recovers RUNNING workflows from the durable checkpoint store
    (simulates worker restart / lease recovery).
    """

    def __init__(self, settings: WorkerSettings) -> None:
        self.settings = settings
        self._running = False

    def start(self) -> None:
        self._running = True
        logger.info(
            "mock_worker_started",
            mode=self.settings.workflow_mode,
            queue=self.settings.temporal_task_queue,
        )

        def _stop(_signum: int, _frame: FrameType | None) -> None:
            self._running = False

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        while self._running:
            self._recover_running()
            time.sleep(1)

        logger.info("mock_worker_stopped")

    def _recover_running(self) -> None:
        try:
            from app.database.memory import get_memory_store
            from app.workflows.engine import get_mock_engine
            from app.workflows.models import WorkflowStatus
        except ImportError:
            return

        store = get_memory_store()
        engine = get_mock_engine()
        for raw in list(store.workflow_instances.values()):
            if raw.get("status") == WorkflowStatus.RUNNING.value:
                try:
                    from uuid import UUID

                    engine.recover(UUID(raw["id"]))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("workflow_recovery_failed", error=str(exc), workflow_id=raw.get("id"))

    def health(self) -> dict[str, str]:
        return {"status": "ok", "mode": "mock"}


def run_temporal_worker(settings: WorkerSettings) -> None:
    """Connect to Temporal Cloud and poll the task queue (no local Temporal server)."""
    try:
        from temporalio.client import Client
        from temporalio.worker import Worker
    except ImportError as exc:
        raise RuntimeError(
            "temporalio is required for WORKFLOW_MODE=temporal. Install with: pip install temporalio"
        ) from exc

    import asyncio

    async def _run() -> None:
        if settings.temporal_api_key:
            client = await Client.connect(
                settings.temporal_host or "",
                namespace=settings.temporal_namespace or "",
                api_key=settings.temporal_api_key,
                tls=True,
            )
        else:
            client = await Client.connect(
                settings.temporal_host or "",
                namespace=settings.temporal_namespace or "",
            )

        # Activities/workflows are registered from the API package when available.
        try:
            from app.workflows.temporal_worker import BPM_ACTIVITIES, BPMProcessTemporalWorkflow
        except ImportError as exc:
            raise RuntimeError(
                "BPM Temporal workflow definitions require bpm-api on PYTHONPATH. "
                "Install services/api into the same venv."
            ) from exc

        worker = Worker(
            client,
            task_queue=settings.temporal_task_queue,
            workflows=[BPMProcessTemporalWorkflow],
            activities=BPM_ACTIVITIES,
        )
        logger.info(
            "temporal_worker_started",
            namespace=settings.temporal_namespace,
            queue=settings.temporal_task_queue,
        )
        await worker.run()

    asyncio.run(_run())


def run_worker(settings: WorkerSettings) -> None:
    if settings.workflow_mode == "temporal":
        if not settings.temporal_host or not settings.temporal_namespace:
            raise RuntimeError(
                "WORKFLOW_MODE=temporal requires TEMPORAL_HOST and TEMPORAL_NAMESPACE"
            )
        run_temporal_worker(settings)
        return
    MockWorkflowRunner(settings).start()
