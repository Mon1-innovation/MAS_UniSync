from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest


sys.dont_write_bytecode = True
CLIENT_DIR = Path("game/Submods/MAS_UniSync")


def load_client_module(name: str):
    path = CLIENT_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_api_url_normalization_preserves_full_urls_and_migrates_legacy_hosts():
    core = load_client_module("mas_unisync_core")

    assert core.normalize_api_url(" https://api.example.test:8443/base/ ") == "https://api.example.test:8443/base"
    assert core.normalize_api_url("http://100.72.137.92:9000") == "http://100.72.137.92:9000"
    assert core.normalize_api_url("100.72.137.92") == "http://100.72.137.92:8000"
    assert core.normalize_api_url("100.72.137.92:9000") == "http://100.72.137.92:9000"
    assert core.api_base_url("https://api.example.test:8443/base/") == "https://api.example.test:8443/base"


def test_multipart_body_contains_file_and_optional_version_metadata(tmp_path):
    http = load_client_module("mas_unisync_http")
    upload_file = tmp_path / "persistent"
    upload_file.write_bytes(b"save-data")

    body, content_type = http.build_multipart_form_data(
        str(upload_file),
        renpy_version="8.2.3",
        mas_version="0.12.15",
        boundary="BOUNDARY",
    )

    assert content_type == "multipart/form-data; boundary=BOUNDARY"
    assert b'name="file"; filename="persistent"' in body
    assert b"Content-Type: application/octet-stream" in body
    assert b"save-data" in body
    assert b'name="renpy_version"' in body
    assert b"\r\n\r\n8.2.3\r\n" in body
    assert b'name="mas_version"' in body
    assert b"\r\n\r\n0.12.15\r\n" in body


def test_http_error_description_prefers_machine_readable_detail():
    http = load_client_module("mas_unisync_http")

    assert http.describe_error_body(b'{"detail":{"code":"banned","reason":"testing"}}') == (
        '{"detail": {"code": "banned", "reason": "testing"}}'
    )
    assert http.describe_error_body(b"plain failure") == "plain failure"
    assert http.describe_error_body(b"") == "no response body"


def test_display_text_escapes_braces_used_by_renpy_substitution():
    core = load_client_module("mas_unisync_core")

    assert core.renpy_display_text('{"detail": {"code": "banned"}}') == (
        '{{"detail": {{"code": "banned"}}}}'
    )
    assert core.renpy_display_text(None) == ""


def test_backup_rotation_keeps_latest_ten_files(tmp_path):
    core = load_client_module("mas_unisync_core")
    backup_dir = tmp_path / "unisync_backups"
    persistent_file = tmp_path / "persistent"

    for index in range(12):
        persistent_file.write_bytes(f"payload-{index}".encode("ascii"))
        core.create_local_backup(
            str(persistent_file),
            str(backup_dir),
            timestamp=dt.datetime(2026, 1, 1, 12, 0, index),
        )

    backups = sorted(backup_dir.iterdir())
    assert len(backups) == 10
    assert backups[0].name.startswith("20260101-120002-")
    assert backups[-1].name.startswith("20260101-120011-")


def test_upload_state_skips_duplicate_hashes():
    core = load_client_module("mas_unisync_core")
    state = core.SyncStatus()

    assert state.should_upload_hash("abc") is True
    state.mark_upload_success("abc", "2026-01-01T00:00:00")
    assert state.should_upload_hash("abc") is False
    assert state.should_upload_hash("def") is True


def test_persistent_guard_accepts_defaultdict():
    from collections import defaultdict
    guard = load_client_module("mas_unisync_guard")

    data = {"_mas_affection": defaultdict(int, {"love": 100})}
    ok, reason = guard.validate_persistent_dict(data)
    assert ok, reason


def test_persistent_guard_accepts_deque():
    from collections import deque
    guard = load_client_module("mas_unisync_guard")

    data = {"history": deque([1, 2, 3])}
    ok, reason = guard.validate_persistent_dict(data)
    assert ok, reason


def test_persistent_guard_accepts_preferences_type():
    guard = load_client_module("mas_unisync_guard")

    class Preferences:
        pass
    Preferences.__name__ = "Preferences"

    data = {"_preferences": Preferences()}
    ok, reason = guard.validate_persistent_dict(data)
    assert ok, reason


def test_persistent_guard_accepts_safe_types_and_rejects_custom_instances():
    guard = load_client_module("mas_unisync_guard")

    safe = {
        "name": "Monika",
        "visits": 10,
        "dates": [dt.date(2026, 1, 1), dt.datetime(2026, 1, 1, 12, 0)],
        "flags": {"seen": True, "none": None},
    }
    assert guard.validate_persistent_dict(safe) == (True, "")

    class UnsafeThing:
        pass

    valid, reason = guard.validate_persistent_dict({"bad": UnsafeThing()})
    assert valid is False
    assert "bad" in reason


def test_persistent_guard_rejects_timezone_aware_datetime_and_recursive_data():
    guard = load_client_module("mas_unisync_guard")

    valid, reason = guard.validate_persistent_dict(
        {"when": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)}
    )
    assert valid is False
    assert "timezone" in reason

    recursive = []
    recursive.append(recursive)
    valid, reason = guard.validate_persistent_dict({"loop": recursive})
    assert valid is False
    assert "recursive" in reason
