from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mas_unisync_server.main import create_app
from mas_unisync_server.settings import build_settings


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MAS UniSync API with local .env settings.")
    parser.add_argument("--env-file", default=PROJECT_ROOT / ".env", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()

    load_env_file(args.env_file)
    uvicorn.run(create_app(build_settings()), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
