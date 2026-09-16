from workflow_worker.runner import MockWorkflowRunner
from workflow_worker.settings import WorkerSettings


def test_mock_runner_health() -> None:
    runner = MockWorkflowRunner(WorkerSettings(workflow_mode="mock"))
    assert runner.health()["mode"] == "mock"


def test_contracts_importable_from_worker() -> None:
    from bpm_contracts import HealthResponse

    assert HealthResponse(service="worker", version="0.1.0").status == "ok"
