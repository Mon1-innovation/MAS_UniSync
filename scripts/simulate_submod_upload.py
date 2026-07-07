from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import uuid
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request


VERSION_FIELDS = (
    "id",
    "profile_id",
    "sha256",
    "size",
    "renpy_version",
    "mas_version",
    "created_at",
)

ENV_ALIASES = {
    "server_url": ("MAS_UNISYNC_SERVER_URL", "SERVER_URL"),
    "profile_key": ("MAS_UNISYNC_PROFILE_KEY", "PROFILE_KEY"),
    "file": ("MAS_UNISYNC_UPLOAD_FILE", "UPLOAD_FILE", "FILE"),
    "renpy_version": ("MAS_UNISYNC_RENPY_VERSION", "RENPY_VERSION"),
    "mas_version": ("MAS_UNISYNC_MAS_VERSION", "MAS_VERSION"),
    "keep_lock": ("MAS_UNISYNC_KEEP_LOCK", "KEEP_LOCK"),
}


class UploadSimulationError(Exception):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate a MAS submod persistent upload.")
    parser.add_argument("--env-file", type=Path, help="Dotenv-style file to read options from; defaults to .env if present")
    parser.add_argument("--server-url", help="Base server URL, for example http://127.0.0.1:8000")
    parser.add_argument("--profile-key", help="MAS profile key to authenticate the upload")
    parser.add_argument("--file", type=Path, help="Path to the persistent file to upload")
    parser.add_argument("--renpy-version", help="Optional Ren'Py version metadata")
    parser.add_argument("--mas-version", help="Optional MAS version metadata")
    parser.add_argument("--keep-lock", action="store_true", default=None, help="Do not release the acquired lease after upload")
    return parser.parse_args(argv)


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            raise UploadSimulationError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise UploadSimulationError(f"{path}:{line_number}: environment variable name is empty")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def env_value(env: dict[str, str], name: str) -> str | None:
    for alias in ENV_ALIASES[name]:
        if alias in env and env[alias] != "":
            return env[alias]
    return None


def parse_env_bool(value: str, *, variable_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise UploadSimulationError(f"{variable_name} must be one of: 1, 0, true, false, yes, no, on, off")


def resolve_args(args: argparse.Namespace) -> argparse.Namespace:
    env_path = args.env_file
    env: dict[str, str] = {}
    if env_path is None:
        default_env = Path(".env")
        required_args_missing = args.server_url is None or args.profile_key is None or args.file is None
        if required_args_missing and default_env.is_file():
            env_path = default_env
    elif not env_path.is_file():
        raise UploadSimulationError(f"env file not found: {env_path}")

    if env_path is not None:
        env = load_env_file(env_path)

    if args.server_url is None:
        args.server_url = env_value(env, "server_url")
    if args.profile_key is None:
        args.profile_key = env_value(env, "profile_key")
    if args.file is None:
        file_value = env_value(env, "file")
        args.file = Path(file_value) if file_value is not None else None
    if args.renpy_version is None:
        args.renpy_version = env_value(env, "renpy_version")
    if args.mas_version is None:
        args.mas_version = env_value(env, "mas_version")
    if args.keep_lock is None:
        keep_lock_value = env_value(env, "keep_lock")
        args.keep_lock = parse_env_bool(keep_lock_value, variable_name=ENV_ALIASES["keep_lock"][0]) if keep_lock_value else False

    missing = [flag for flag, value in (("--server-url", args.server_url), ("--profile-key", args.profile_key), ("--file", args.file)) if value is None]
    if missing:
        raise UploadSimulationError(f"missing required options: {', '.join(missing)}")
    return args


def build_url(server_url: str, path: str) -> str:
    return f"{server_url.rstrip('/')}/{path.lstrip('/')}"


def build_multipart_form_data(
    file_path: Path,
    *,
    renpy_version: str | None = None,
    mas_version: str | None = None,
    boundary: str | None = None,
) -> tuple[bytes, str]:
    boundary = boundary or uuid.uuid4().hex
    chunks: list[bytes] = []

    def add_text_field(name: str, value: str) -> None:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    for name, value in (("renpy_version", renpy_version), ("mas_version", mas_version)):
        if value is not None:
            add_text_field(name, value)

    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("ascii"),
            (
                f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8"),
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def parse_json_body(body: bytes) -> dict | None:
    if not body:
        return None
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def describe_error_body(body: bytes) -> str:
    parsed = parse_json_body(body)
    if parsed is not None:
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    if body:
        return body.decode("utf-8", errors="replace")
    return "no response body"


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    urlopen=urllib_request.urlopen,
) -> dict | None:
    request = urllib_request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            status = response.getcode()
            body = response.read()
    except urllib_error.HTTPError as exc:
        body = exc.read()
        detail = describe_error_body(body)
        raise UploadSimulationError(f"{method} {url} failed with HTTP {exc.code}: {detail}") from exc
    except urllib_error.URLError as exc:
        raise UploadSimulationError(f"{method} {url} failed: {exc.reason}") from exc

    if status < 200 or status >= 300:
        detail = describe_error_body(body)
        raise UploadSimulationError(f"{method} {url} failed with HTTP {status}: {detail}")
    return parse_json_body(body)


def acquire_lock(server_url: str, profile_key: str, *, urlopen=urllib_request.urlopen) -> str:
    payload = request_json(
        "POST",
        build_url(server_url, "/v1/locks/acquire"),
        headers={"X-MAS-Profile-Key": profile_key},
        data=b"",
        urlopen=urlopen,
    )
    if not payload or not isinstance(payload.get("lease_token"), str):
        raise UploadSimulationError("lock acquisition response did not include lease_token")
    return payload["lease_token"]


def upload_persistent(args: argparse.Namespace, lease_token: str, *, urlopen=urllib_request.urlopen) -> dict:
    body, content_type = build_multipart_form_data(
        args.file,
        renpy_version=args.renpy_version,
        mas_version=args.mas_version,
    )
    payload = request_json(
        "POST",
        build_url(args.server_url, "/v1/persistent/upload"),
        headers={
            "X-MAS-Profile-Key": args.profile_key,
            "X-MAS-Lease-Token": lease_token,
            "Content-Type": content_type,
        },
        data=body,
        urlopen=urlopen,
    )
    if not isinstance(payload, dict):
        raise UploadSimulationError("upload response did not include JSON metadata")
    return payload


def release_lock(server_url: str, profile_key: str, lease_token: str, *, urlopen=urllib_request.urlopen) -> None:
    request_json(
        "POST",
        build_url(server_url, "/v1/locks/release"),
        headers={"X-MAS-Profile-Key": profile_key, "X-MAS-Lease-Token": lease_token},
        data=b"",
        urlopen=urlopen,
    )


def print_version_metadata(metadata: dict) -> None:
    for field in VERSION_FIELDS:
        print(f"{field}: {metadata.get(field)}")


def run(argv: list[str] | None = None, *, urlopen=urllib_request.urlopen) -> int:
    try:
        args = resolve_args(parse_args(argv))
    except UploadSimulationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not args.file.is_file():
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 1

    lease_token: str | None = None
    primary_error: UploadSimulationError | None = None
    try:
        lease_token = acquire_lock(args.server_url, args.profile_key, urlopen=urlopen)
        metadata = upload_persistent(args, lease_token, urlopen=urlopen)
        print_version_metadata(metadata)
    except UploadSimulationError as exc:
        primary_error = exc
    finally:
        if lease_token and not args.keep_lock:
            try:
                release_lock(args.server_url, args.profile_key, lease_token, urlopen=urlopen)
            except UploadSimulationError as exc:
                if primary_error is None:
                    primary_error = exc
                else:
                    print(f"warning: failed to release lease: {exc}", file=sys.stderr)

    if primary_error is not None:
        print(f"error: {primary_error}", file=sys.stderr)
        return 1
    if args.keep_lock and lease_token:
        print(f"lease_token: {lease_token}")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
