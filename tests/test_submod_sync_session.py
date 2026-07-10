from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.error import HTTPError

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


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, body: bytes | None = None):
        self.status = status
        self.payload = payload
        self.body = body

    def getcode(self):
        return self.status

    def read(self):
        if self.body is not None:
            return self.body
        if self.payload is None:
            return b""
        return json.dumps(self.payload).encode("utf-8")

    def close(self):
        pass


def header(request, name: str) -> str | None:
    wanted = name.lower()
    for key, value in request.header_items():
        if key.lower() == wanted:
            return value
    return None


def test_sync_session_acquires_lock_uploads_and_releases(tmp_path):
    sync = load_client_module("mas_unisync_sync")
    persistent = tmp_path / "persistent"
    persistent.write_bytes(b"local")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/profile/resolve"):
            return FakeResponse(200, {"profile": {"id": 7}})
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_123"})
        if request.full_url.endswith("/v1/persistent/current"):
            raise HTTPError(
                request.full_url,
                404,
                "Not Found",
                hdrs=None,
                fp=FakeResponse(404, {"detail": {"code": "no_current_persistent"}}),
            )
        if request.full_url.endswith("/v1/persistent/upload"):
            return FakeResponse(201, {"sha256": "localhash", "created_at": "2026-01-01T00:00:00Z"})
        if request.full_url.endswith("/v1/locks/release"):
            return FakeResponse(204)
        raise AssertionError(f"unexpected URL {request.full_url}")

    session = sync.SyncSession("100.72.137.92", "maspk_test", str(persistent), urlopen=fake_urlopen)
    session.start()
    session.upload_if_changed()
    session.release()

    assert [request.full_url for request in requests] == [
        "http://100.72.137.92:8000/v1/profile/resolve",
        "http://100.72.137.92:8000/v1/locks/acquire",
        "http://100.72.137.92:8000/v1/persistent/current",
        "http://100.72.137.92:8000/v1/persistent/upload",
        "http://100.72.137.92:8000/v1/locks/release",
    ]
    assert header(requests[0], "X-MAS-Profile-Key") == "maspk_test"
    assert header(requests[3], "X-MAS-Lease-Token") == "lease_123"
    assert b'name="file"; filename="persistent"' in requests[3].data
    assert session.status.lock_state == "released"
    assert session.status.last_upload_at == "2026-01-01T00:00:00Z"


def test_sync_session_uses_complete_api_url_without_adding_fixed_port(tmp_path):
    sync = load_client_module("mas_unisync_sync")
    persistent = tmp_path / "persistent"
    persistent.write_bytes(b"local")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/profile/resolve"):
            return FakeResponse(200, {"profile": {"id": 7}})
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_123"})
        if request.full_url.endswith("/v1/persistent/current"):
            raise HTTPError(
                request.full_url,
                404,
                "Not Found",
                hdrs=None,
                fp=FakeResponse(404, {"detail": {"code": "no_current_persistent"}}),
            )
        raise AssertionError(f"unexpected URL {request.full_url}")

    session = sync.SyncSession(
        "https://api.example.test:9443/mas-api/",
        "maspk_test",
        str(persistent),
        urlopen=fake_urlopen,
    )
    session.start()

    assert [request.full_url for request in requests] == [
        "https://api.example.test:9443/mas-api/v1/profile/resolve",
        "https://api.example.test:9443/mas-api/v1/locks/acquire",
        "https://api.example.test:9443/mas-api/v1/persistent/current",
    ]


def test_fetch_profile_keys_url_requests_public_config_from_api_url():
    sync = load_client_module("mas_unisync_sync")
    requests = []
    timeouts = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        timeouts.append(timeout)
        if request.full_url == "https://api.example.test/root/v1/config/web-url":
            return FakeResponse(
                200,
                {
                    "frontend_web_url": "https://portal.example.test",
                    "profile_keys_url": "https://portal.example.test/account/profile-keys",
                },
            )
        raise AssertionError(f"unexpected URL {request.full_url}")

    result = sync.fetch_profile_keys_url("https://api.example.test/root/", urlopen=fake_urlopen)

    assert result == "https://portal.example.test/account/profile-keys"
    assert len(requests) == 1
    assert timeouts == [10]


def test_sync_session_requests_use_ten_second_timeout(tmp_path):
    sync = load_client_module("mas_unisync_sync")
    persistent = tmp_path / "persistent"
    persistent.write_bytes(b"local")
    timeouts = []

    def fake_urlopen(request, timeout):
        timeouts.append(timeout)
        if request.full_url.endswith("/v1/profile/resolve"):
            return FakeResponse(200, {"profile": {"id": 7}})
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_123"})
        if request.full_url.endswith("/v1/persistent/current"):
            raise HTTPError(
                request.full_url,
                404,
                "Not Found",
                hdrs=None,
                fp=FakeResponse(404, {"detail": {"code": "no_current_persistent"}}),
            )
        if request.full_url.endswith("/v1/persistent/upload"):
            return FakeResponse(201, {"sha256": "localhash", "created_at": "2026-01-01T00:00:00Z"})
        raise AssertionError(f"unexpected URL {request.full_url}")

    session = sync.SyncSession(
        "100.72.137.92",
        "maspk_test",
        str(persistent),
        urlopen=fake_urlopen,
    )
    session.start(upload_after_sync=True)

    assert timeouts == [10, 10, 10, 10]


def test_acquire_lock_raises_lock_not_held_error_when_server_reports_conflict(tmp_path):
    sync = load_client_module("mas_unisync_sync")
    persistent = tmp_path / "persistent"
    persistent.write_bytes(b"local")

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/v1/locks/acquire"):
            raise HTTPError(
                request.full_url,
                409,
                "Conflict",
                hdrs=None,
                fp=FakeResponse(409, {"detail": {"code": "lock_held"}}),
            )
        raise AssertionError(f"unexpected URL {request.full_url}")

    session = sync.SyncSession(
        "100.72.137.92",
        "maspk_test",
        str(persistent),
        urlopen=fake_urlopen,
    )

    assert issubclass(sync.core.UniSyncLockNotHeldError, sync.core.UniSyncError)
    with pytest.raises(sync.core.UniSyncLockNotHeldError):
        session.acquire_lock()


def test_start_can_upload_local_persistent_when_remote_has_no_current_file(tmp_path):
    sync = load_client_module("mas_unisync_sync")
    persistent = tmp_path / "persistent"
    persistent.write_bytes(b"local")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/profile/resolve"):
            return FakeResponse(200, {"profile": {"id": 7}})
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_123"})
        if request.full_url.endswith("/v1/persistent/current"):
            raise HTTPError(
                request.full_url,
                404,
                "Not Found",
                hdrs=None,
                fp=FakeResponse(404, {"detail": {"code": "no_current_persistent"}}),
            )
        if request.full_url.endswith("/v1/persistent/upload"):
            return FakeResponse(201, {"sha256": "localhash", "created_at": "2026-01-01T00:00:00Z"})
        raise AssertionError(f"unexpected URL {request.full_url}")

    session = sync.SyncSession("100.72.137.92", "maspk_test", str(persistent), urlopen=fake_urlopen)
    session.start(upload_after_sync=True)

    assert [request.full_url for request in requests] == [
        "http://100.72.137.92:8000/v1/profile/resolve",
        "http://100.72.137.92:8000/v1/locks/acquire",
        "http://100.72.137.92:8000/v1/persistent/current",
        "http://100.72.137.92:8000/v1/persistent/upload",
    ]
    assert header(requests[3], "X-MAS-Lease-Token") == "lease_123"
    assert b'name="file"; filename="persistent"' in requests[3].data
    assert session.status.last_upload_at == "2026-01-01T00:00:00Z"


def test_start_upload_after_sync_always_posts_even_when_hash_was_uploaded(tmp_path):
    sync = load_client_module("mas_unisync_sync")
    core = load_client_module("mas_unisync_core")
    persistent = tmp_path / "persistent"
    persistent.write_bytes(b"local")
    local_hash = core.sha256_file(str(persistent))
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/profile/resolve"):
            return FakeResponse(200, {"profile": {"id": 7}})
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_123"})
        if request.full_url.endswith("/v1/persistent/current"):
            raise HTTPError(
                request.full_url,
                404,
                "Not Found",
                hdrs=None,
                fp=FakeResponse(404, {"detail": {"code": "no_current_persistent"}}),
            )
        if request.full_url.endswith("/v1/persistent/upload"):
            return FakeResponse(201, {"sha256": local_hash, "created_at": "2026-01-01T00:00:00Z"})
        raise AssertionError(f"unexpected URL {request.full_url}")

    session = sync.SyncSession("100.72.137.92", "maspk_test", str(persistent), urlopen=fake_urlopen)
    session.status.mark_upload_success(local_hash, "2025-01-01T00:00:00Z")
    session.start(upload_after_sync=True)

    assert [request.full_url for request in requests] == [
        "http://100.72.137.92:8000/v1/profile/resolve",
        "http://100.72.137.92:8000/v1/locks/acquire",
        "http://100.72.137.92:8000/v1/persistent/current",
        "http://100.72.137.92:8000/v1/persistent/upload",
    ]
    assert header(requests[3], "X-MAS-Lease-Token") == "lease_123"
    assert b'name="file"; filename="persistent"' in requests[3].data
    assert session.status.last_upload_at == "2026-01-01T00:00:00Z"


def test_sync_session_downloads_cloud_first_when_remote_hash_differs(tmp_path):
    sync = load_client_module("mas_unisync_sync")
    persistent = tmp_path / "persistent"
    persistent.write_bytes(b"local")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/profile/resolve"):
            return FakeResponse(200, {"profile": {"id": 7}})
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_123"})
        if request.full_url.endswith("/v1/persistent/current"):
            return FakeResponse(200, {"sha256": "remotehash", "created_at": "2026-01-01T00:00:00Z"})
        if request.full_url.endswith("/v1/persistent/download"):
            return FakeResponse(200, body=b"cloud")
        raise AssertionError(f"unexpected URL {request.full_url}")

    session = sync.SyncSession("100.72.137.92", "maspk_test", str(persistent), urlopen=fake_urlopen)
    session.start()

    assert persistent.read_bytes() == b"cloud"
    assert not (tmp_path / "backups").exists()
    assert requests[-1].full_url == "http://100.72.137.92:8000/v1/persistent/download"
    assert session.status.last_download_at


def test_start_can_load_remote_persistent_into_memory_without_replacing_local_file(monkeypatch, tmp_path):
    sync = load_client_module("mas_unisync_sync")
    persistent = tmp_path / "persistent"
    persistent.write_bytes(b"local")
    requests = []
    loaded_bodies = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/profile/resolve"):
            return FakeResponse(200, {"profile": {"id": 7}})
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_123"})
        if request.full_url.endswith("/v1/persistent/current"):
            return FakeResponse(200, {"sha256": "remotehash", "created_at": "2026-01-01T00:00:00Z"})
        if request.full_url.endswith("/v1/persistent/download"):
            return FakeResponse(200, body=b"cloud")
        if request.full_url.endswith("/v1/locks/release"):
            raise AssertionError("successful memory load should keep the startup lease")
        raise AssertionError(f"unexpected URL {request.full_url}")

    def fake_load_persistent(data):
        loaded_bodies.append(data)

    monkeypatch.setattr(sync.core, "load_persistent_bytes_into_renpy", fake_load_persistent)

    session = sync.SyncSession("100.72.137.92", "maspk_test", str(persistent), urlopen=fake_urlopen)
    session.start(load_remote_into_memory=True)

    assert loaded_bodies == [b"cloud"]
    assert persistent.read_bytes() == b"local"
    assert [request.full_url for request in requests] == [
        "http://100.72.137.92:8000/v1/profile/resolve",
        "http://100.72.137.92:8000/v1/locks/acquire",
        "http://100.72.137.92:8000/v1/persistent/current",
        "http://100.72.137.92:8000/v1/persistent/download",
    ]
    assert session.status.lock_state == "locked"
    assert session.status.last_local_hash == "remotehash"


def test_start_releases_lease_when_memory_load_fails(monkeypatch, tmp_path):
    sync = load_client_module("mas_unisync_sync")
    persistent = tmp_path / "persistent"
    persistent.write_bytes(b"local")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/profile/resolve"):
            return FakeResponse(200, {"profile": {"id": 7}})
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_123"})
        if request.full_url.endswith("/v1/persistent/current"):
            return FakeResponse(200, {"sha256": "remotehash", "created_at": "2026-01-01T00:00:00Z"})
        if request.full_url.endswith("/v1/persistent/download"):
            return FakeResponse(200, body=b"cloud")
        if request.full_url.endswith("/v1/locks/release"):
            return FakeResponse(204)
        raise AssertionError(f"unexpected URL {request.full_url}")

    def fail_load_persistent(data):
        raise ValueError("bad persistent")

    monkeypatch.setattr(sync.core, "load_persistent_bytes_into_renpy", fail_load_persistent)

    session = sync.SyncSession("100.72.137.92", "maspk_test", str(persistent), urlopen=fake_urlopen)

    with pytest.raises(ValueError, match="bad persistent"):
        session.start(load_remote_into_memory=True)

    assert persistent.read_bytes() == b"local"
    assert [request.full_url for request in requests] == [
        "http://100.72.137.92:8000/v1/profile/resolve",
        "http://100.72.137.92:8000/v1/locks/acquire",
        "http://100.72.137.92:8000/v1/persistent/current",
        "http://100.72.137.92:8000/v1/persistent/download",
        "http://100.72.137.92:8000/v1/locks/release",
    ]
    assert session.status.lock_state == "released"


def test_start_upload_after_sync_uploads_even_after_downloading_remote_file(tmp_path):
    sync = load_client_module("mas_unisync_sync")
    persistent = tmp_path / "persistent"
    persistent.write_bytes(b"local")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/profile/resolve"):
            return FakeResponse(200, {"profile": {"id": 7}})
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_123"})
        if request.full_url.endswith("/v1/persistent/current"):
            return FakeResponse(200, {"sha256": "remotehash", "created_at": "2026-01-01T00:00:00Z"})
        if request.full_url.endswith("/v1/persistent/download"):
            return FakeResponse(200, body=b"cloud")
        if request.full_url.endswith("/v1/persistent/upload"):
            return FakeResponse(201, {"sha256": "remotehash", "created_at": "2026-01-01T00:00:00Z"})
        raise AssertionError(f"unexpected URL {request.full_url}")

    session = sync.SyncSession("100.72.137.92", "maspk_test", str(persistent), urlopen=fake_urlopen)
    session.start(upload_after_sync=True)

    assert persistent.read_bytes() == b"cloud"
    assert [request.full_url for request in requests] == [
        "http://100.72.137.92:8000/v1/profile/resolve",
        "http://100.72.137.92:8000/v1/locks/acquire",
        "http://100.72.137.92:8000/v1/persistent/current",
        "http://100.72.137.92:8000/v1/persistent/download",
        "http://100.72.137.92:8000/v1/persistent/upload",
    ]
    assert header(requests[4], "X-MAS-Lease-Token") == "lease_123"
