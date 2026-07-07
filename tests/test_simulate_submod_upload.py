from __future__ import annotations

import json
from urllib.error import HTTPError

from scripts import simulate_submod_upload as sim


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None):
        self.status = status
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return self.status

    def read(self):
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


def test_multipart_body_includes_file_and_version_fields(tmp_path):
    upload_file = tmp_path / "persistent"
    upload_file.write_bytes(b"save-data")

    body, content_type = sim.build_multipart_form_data(
        upload_file,
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


def test_run_acquires_uploads_with_lease_and_releases_after_success(tmp_path, capsys):
    upload_file = tmp_path / "persistent"
    upload_file.write_bytes(b"save-data")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_123"})
        if request.full_url.endswith("/v1/persistent/upload"):
            return FakeResponse(
                201,
                {
                    "id": 42,
                    "profile_id": 7,
                    "sha256": "abc123",
                    "size": 9,
                    "renpy_version": "8.2.3",
                    "mas_version": "0.12.15",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            )
        if request.full_url.endswith("/v1/locks/release"):
            return FakeResponse(204)
        raise AssertionError(f"unexpected URL {request.full_url}")

    exit_code = sim.run(
        [
            "--server-url",
            "http://127.0.0.1:8000/",
            "--profile-key",
            "maspk_test",
            "--file",
            str(upload_file),
            "--renpy-version",
            "8.2.3",
            "--mas-version",
            "0.12.15",
        ],
        urlopen=fake_urlopen,
    )

    assert exit_code == 0
    assert [request.full_url for request in requests] == [
        "http://127.0.0.1:8000/v1/locks/acquire",
        "http://127.0.0.1:8000/v1/persistent/upload",
        "http://127.0.0.1:8000/v1/locks/release",
    ]
    upload = requests[1]
    assert header(upload, "X-MAS-Profile-Key") == "maspk_test"
    assert header(upload, "X-MAS-Lease-Token") == "lease_123"
    assert b'name="file"; filename="persistent"' in upload.data
    output = capsys.readouterr().out
    assert "id: 42" in output
    assert "sha256: abc123" in output


def test_run_reads_upload_options_from_env_file(tmp_path):
    upload_file = tmp_path / "persistent"
    upload_file.write_bytes(b"save-data")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "MAS_UNISYNC_SERVER_URL=http://127.0.0.1:8000",
                "MAS_UNISYNC_PROFILE_KEY=maspk_env",
                f"MAS_UNISYNC_UPLOAD_FILE={upload_file}",
                "MAS_UNISYNC_RENPY_VERSION=8.2.3",
                "MAS_UNISYNC_MAS_VERSION=0.12.15",
            ]
        ),
        encoding="utf-8",
    )
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_env"})
        if request.full_url.endswith("/v1/persistent/upload"):
            return FakeResponse(201, {"id": 1})
        if request.full_url.endswith("/v1/locks/release"):
            return FakeResponse(204)
        raise AssertionError(f"unexpected URL {request.full_url}")

    exit_code = sim.run(["--env-file", str(env_file)], urlopen=fake_urlopen)

    assert exit_code == 0
    acquire, upload, release = requests
    assert acquire.full_url == "http://127.0.0.1:8000/v1/locks/acquire"
    assert header(acquire, "X-MAS-Profile-Key") == "maspk_env"
    assert header(upload, "X-MAS-Profile-Key") == "maspk_env"
    assert header(upload, "X-MAS-Lease-Token") == "lease_env"
    assert b"\r\n\r\n8.2.3\r\n" in upload.data
    assert b"\r\n\r\n0.12.15\r\n" in upload.data
    assert header(release, "X-MAS-Profile-Key") == "maspk_env"


def test_cli_options_override_env_file_values(tmp_path):
    env_upload = tmp_path / "env-persistent"
    cli_upload = tmp_path / "cli-persistent"
    env_upload.write_bytes(b"env-data")
    cli_upload.write_bytes(b"cli-data")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "MAS_UNISYNC_SERVER_URL=http://env.example",
                "MAS_UNISYNC_PROFILE_KEY=maspk_env",
                f"MAS_UNISYNC_UPLOAD_FILE={env_upload}",
            ]
        ),
        encoding="utf-8",
    )
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_cli"})
        if request.full_url.endswith("/v1/persistent/upload"):
            return FakeResponse(201, {"id": 1})
        if request.full_url.endswith("/v1/locks/release"):
            return FakeResponse(204)
        raise AssertionError(f"unexpected URL {request.full_url}")

    exit_code = sim.run(
        [
            "--env-file",
            str(env_file),
            "--server-url",
            "http://cli.example",
            "--profile-key",
            "maspk_cli",
            "--file",
            str(cli_upload),
        ],
        urlopen=fake_urlopen,
    )

    assert exit_code == 0
    assert requests[0].full_url == "http://cli.example/v1/locks/acquire"
    assert header(requests[0], "X-MAS-Profile-Key") == "maspk_cli"
    assert b"cli-data" in requests[1].data
    assert b"env-data" not in requests[1].data


def test_run_exits_nonzero_and_still_releases_after_upload_failure(tmp_path, capsys):
    upload_file = tmp_path / "persistent"
    upload_file.write_bytes(b"save-data")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_123"})
        if request.full_url.endswith("/v1/persistent/upload"):
            raise HTTPError(
                request.full_url,
                500,
                "Internal Server Error",
                hdrs=None,
                fp=FakeResponse(500, {"detail": {"code": "upload_failed"}}),
            )
        if request.full_url.endswith("/v1/locks/release"):
            return FakeResponse(204)
        raise AssertionError(f"unexpected URL {request.full_url}")

    exit_code = sim.run(
        [
            "--server-url",
            "http://127.0.0.1:8000",
            "--profile-key",
            "maspk_test",
            "--file",
            str(upload_file),
        ],
        urlopen=fake_urlopen,
    )

    assert exit_code == 1
    assert [request.full_url for request in requests] == [
        "http://127.0.0.1:8000/v1/locks/acquire",
        "http://127.0.0.1:8000/v1/persistent/upload",
        "http://127.0.0.1:8000/v1/locks/release",
    ]
    assert "upload_failed" in capsys.readouterr().err


def test_keep_lock_skips_release(tmp_path):
    upload_file = tmp_path / "persistent"
    upload_file.write_bytes(b"save-data")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/v1/locks/acquire"):
            return FakeResponse(200, {"lease_token": "lease_123"})
        if request.full_url.endswith("/v1/persistent/upload"):
            return FakeResponse(201, {"id": 1})
        raise AssertionError(f"unexpected URL {request.full_url}")

    exit_code = sim.run(
        [
            "--server-url",
            "http://127.0.0.1:8000",
            "--profile-key",
            "maspk_test",
            "--file",
            str(upload_file),
            "--keep-lock",
        ],
        urlopen=fake_urlopen,
    )

    assert exit_code == 0
    assert [request.full_url for request in requests] == [
        "http://127.0.0.1:8000/v1/locks/acquire",
        "http://127.0.0.1:8000/v1/persistent/upload",
    ]
