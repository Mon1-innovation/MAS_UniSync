from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mas_unisync_server.flarum import FlarumClient
from mas_unisync_server.services import map_role
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


def masked_token(token: str) -> str:
    if len(token) <= 12:
        return "***"
    return f"{token[:6]}...{token[-6:]}"


async def run_probe(args: argparse.Namespace) -> int:
    load_env_file(Path(args.env_file))

    forum_url = args.forum_url or os.getenv("FLARUM_URL")
    if not forum_url:
        print("Missing forum URL. Pass --forum-url or set FLARUM_URL.")
        return 2

    identification = args.identification or os.getenv("FLARUM_TEST_IDENTIFICATION") or input("Flarum account/email: ").strip()
    password = args.password or os.getenv("FLARUM_TEST_PASSWORD") or getpass.getpass("Flarum password: ")

    settings = Settings(
        flarum_url=forum_url,
        admin_flarum_group_ids=parse_csv_set(args.admin_group_ids or os.getenv("ADMIN_FLARUM_GROUP_IDS")),
        admin_flarum_group_names=parse_csv_set(args.admin_group_names or os.getenv("ADMIN_FLARUM_GROUP_NAMES")),
    )

    client = FlarumClient(settings.flarum_url)
    try:
        token_payload = await client.login(identification, password)
        user = await client.get_user(token_payload["token"], str(token_payload["user_id"]))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    output = {
        "ok": True,
        "forum_url": settings.flarum_url,
        "token": token_payload["token"] if args.show_token else masked_token(token_payload["token"]),
        "flarum_user_id": user["flarum_user_id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "avatar_url": user["avatar_url"],
        "groups": user["groups"],
        "mapped_role": map_role(user["groups"], settings),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Flarum login and print imported MAS UniSync user info.")
    parser.add_argument("--forum-url", help="Flarum base URL, for example https://forum.example")
    parser.add_argument("--identification", help="Flarum username or email. If omitted, prompts interactively.")
    parser.add_argument("--password", help="Flarum password. Prefer interactive prompt or env-safe wrappers.")
    parser.add_argument("--admin-group-ids", help="Comma-separated admin group ids. Defaults to ADMIN_FLARUM_GROUP_IDS.")
    parser.add_argument("--admin-group-names", help="Comma-separated admin group names. Defaults to ADMIN_FLARUM_GROUP_NAMES.")
    parser.add_argument("--env-file", default=PROJECT_ROOT / ".env", type=Path, help="Env file to load before probing. Defaults to .env.")
    parser.add_argument("--show-token", action="store_true", help="Print the raw Flarum token instead of a masked token.")
    args = parser.parse_args()
    return asyncio.run(run_probe(args))


if __name__ == "__main__":
    raise SystemExit(main())
