from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mas_unisync_server.main import create_app
from mas_unisync_server.settings import Settings


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


def parse_csv_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in re.split(r"[,，;；]", value) if item.strip()}


def build_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/mas_unisync.db"),
        object_storage_path=Path(os.getenv("OBJECT_STORAGE_PATH", "./data/objects")),
        session_secret=os.getenv("SESSION_SECRET", "local-dev-session"),
        flarum_url=os.getenv("FLARUM_URL", "https://forum.example"),
        admin_flarum_group_ids=parse_csv_set(os.getenv("ADMIN_FLARUM_GROUP_IDS")),
        admin_flarum_group_names=parse_csv_set(os.getenv("ADMIN_FLARUM_GROUP_NAMES")),
        lock_ttl_seconds=int(os.getenv("LOCK_TTL_SECONDS", "60")),
    )


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
