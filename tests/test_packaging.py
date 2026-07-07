from __future__ import annotations

import tomllib
from pathlib import Path


def test_runtime_dependencies_include_session_signer() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    dependencies = {
        dependency.split("[", 1)[0].split("=", 1)[0].split("<", 1)[0].split(">", 1)[0].strip()
        for dependency in pyproject["project"]["dependencies"]
    }

    assert "itsdangerous" in dependencies
