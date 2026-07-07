from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.error import HTTPError


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

    session = sync.SyncSession("100.72.137.92", "maspk_test", str(persistent), str(tmp_path / "backups"), urlopen=fake_urlopen)
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

    session = sync.SyncSession("100.72.137.92", "maspk_test", str(persistent), str(tmp_path / "backups"), urlopen=fake_urlopen)
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

    session = sync.SyncSession("100.72.137.92", "maspk_test", str(persistent), str(tmp_path / "backups"), urlopen=fake_urlopen)
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

    session = sync.SyncSession("100.72.137.92", "maspk_test", str(persistent), str(tmp_path / "backups"), urlopen=fake_urlopen)
    session.start()

    assert persistent.read_bytes() == b"cloud"
    assert len(list((tmp_path / "backups").iterdir())) == 1
    assert requests[-1].full_url == "http://100.72.137.92:8000/v1/persistent/download"
    assert session.status.last_download_at


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

    session = sync.SyncSession("100.72.137.92", "maspk_test", str(persistent), str(tmp_path / "backups"), urlopen=fake_urlopen)
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
