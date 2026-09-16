from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_NAMES = {
    "Dockerfile",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}

FORBIDDEN_SUFFIXES = {
    ".dockerfile",
}


def test_no_docker_related_files_exist() -> None:
    offenders: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        # Ignore virtualenvs and node_modules if present
        parts = set(path.parts)
        if ".venv" in parts or "node_modules" in parts or ".git" in parts:
            continue
        name = path.name
        if name in FORBIDDEN_NAMES or name.lower().endswith(tuple(FORBIDDEN_SUFFIXES)):
            offenders.append(str(path.relative_to(ROOT)))
        if path.suffix in {".yaml", ".yml"} and "k8s" in path.parts:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"Docker/container files are forbidden: {offenders}"


def test_native_scripts_exist_and_are_executable_bits_optional() -> None:
    scripts = [
        "scripts/setup-backend",
        "scripts/setup-frontend",
        "scripts/run-api",
        "scripts/run-worker",
        "scripts/run-frontend",
        "scripts/run-tests",
        "scripts/check",
    ]
    for relative in scripts:
        path = ROOT / relative
        assert path.is_file(), f"Missing native script: {relative}"
        assert path.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
