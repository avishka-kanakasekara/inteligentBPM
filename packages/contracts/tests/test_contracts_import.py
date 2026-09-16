from bpm_contracts import HealthResponse, ReadinessResponse, __version__


def test_health_contract_importable() -> None:
    payload = HealthResponse(service="api", version=__version__)
    assert payload.status == "ok"
    assert payload.model_dump()["service"] == "api"


def test_readiness_contract_importable() -> None:
    payload = ReadinessResponse(
        ready=False,
        service="api",
        checks=[{"name": "settings", "ready": False, "detail": "missing"}],
    )
    assert payload.ready is False
    assert len(payload.checks) == 1
