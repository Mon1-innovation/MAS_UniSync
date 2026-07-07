from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mas_unisync_server.main import create_app
from mas_unisync_server.models import AuditLog, Ban, Lock, PersistentCurrent, PersistentDailyBackup, PersistentVersion, Profile
from mas_unisync_server.settings import Settings


class FakeFlarumClient:
    def __init__(self):
        self.accounts = {
            "admin@example.com": {
                "password": "secret",
                "user_id": "10",
                "username": "admin",
                "display_name": "Admin User",
                "avatar_url": "https://forum.example/avatar/admin.png",
                "groups": [{"id": "1", "name": "Admin"}],
            },
            "user@example.com": {
                "password": "secret",
                "user_id": "20",
                "username": "normal",
                "display_name": "Normal User",
                "avatar_url": "https://forum.example/avatar/user.png",
                "groups": [{"id": "2", "name": "Members"}],
            },
        }

    async def login(self, identification: str, password: str):
        account = self.accounts.get(identification)
        if not account or account["password"] != password:
            raise ValueError("invalid flarum credentials")
        return {
            "token": f"token-{account['user_id']}",
            "user_id": account["user_id"],
        }

    async def get_user(self, token: str, user_id: str):
        for account in self.accounts.values():
            if account["user_id"] == str(user_id):
                return {
                    "flarum_user_id": account["user_id"],
                    "username": account["username"],
                    "display_name": account["display_name"],
                    "avatar_url": account["avatar_url"],
                    "groups": account["groups"],
                }
        raise ValueError("missing user")


@pytest.fixture()
def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'server.db'}",
        object_storage_path=tmp_path / "objects",
        session_secret="test-secret",
        admin_flarum_group_ids={"1"},
        admin_flarum_group_names={"Admin"},
        lock_ttl_seconds=60,
    )
    with TestClient(create_app(settings=settings, flarum_client=FakeFlarumClient())) as test_client:
        yield test_client


def login(client: TestClient, identification: str = "user@example.com", password: str = "secret"):
    response = client.post(
        "/login/flarum",
        json={"identification": identification, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def new_profile(client: TestClient):
    login(client)
    response = client.post("/account/profile-keys", json={"display_name": "Main"})
    assert response.status_code == 201
    return response.json()


def acquire_lock(client: TestClient, key: str):
    response = client.post("/v1/locks/acquire", headers={"X-MAS-Profile-Key": key})
    assert response.status_code == 200
    return response.json()["lease_token"]


def upload_persistent(
    client: TestClient,
    key: str,
    lease: str,
    payload: bytes,
    *,
    now: datetime | None = None,
):
    headers = {
        "X-MAS-Profile-Key": key,
        "X-MAS-Lease-Token": lease,
    }
    if now is not None:
        headers["X-Test-Now"] = now.isoformat()
    return client.post(
        "/v1/persistent/upload",
        headers=headers,
        files={"file": ("persistent", payload, "application/octet-stream")},
        data={"renpy_version": "8.2.3", "mas_version": "0.12.15"},
    )


def test_flarum_login_imports_user_and_maps_admin_role(client):
    admin = login(client, "admin@example.com")

    assert admin["user"]["flarum_user_id"] == "10"
    assert admin["user"]["username"] == "admin"
    assert admin["user"]["avatar_url"].endswith("/admin.png")
    assert admin["user"]["role"] == "admin"

    users = client.get("/admin/users")
    assert users.status_code == 200
    assert users.json()["items"][0]["role"] == "admin"


def test_invalid_flarum_login_returns_401(client):
    response = client.post(
        "/login/flarum",
        json={"identification": "user@example.com", "password": "wrong"},
    )

    assert response.status_code == 401


def test_non_admin_user_gets_user_role_and_admin_apis_forbidden(client):
    result = login(client, "user@example.com")
    profile = new_profile(client)

    assert result["user"]["role"] == "user"
    assert client.get("/admin/users").status_code == 403
    assert client.get(f"/admin/profiles/{profile['id']}/persistent/current").status_code == 403


def test_profile_key_generation_lists_plaintext_and_refresh_invalidates_old_key(client):
    profile = new_profile(client)

    assert profile["profile_key"].startswith("maspk_")
    listed = client.get("/account/profile-keys").json()["items"]
    assert listed[0]["profile_key"] == profile["profile_key"]

    lease = acquire_lock(client, profile["profile_key"])
    upload = upload_persistent(client, profile["profile_key"], lease, b"cloud-v1")
    assert upload.status_code == 201

    refreshed = client.post(f"/account/profile-keys/{profile['id']}/refresh").json()
    assert refreshed["id"] == profile["id"]
    assert refreshed["profile_key"] != profile["profile_key"]
    assert client.get("/v1/profile/resolve", headers={"X-MAS-Profile-Key": profile["profile_key"]}).status_code == 401

    current = client.get("/v1/persistent/current", headers={"X-MAS-Profile-Key": refreshed["profile_key"]})
    assert current.status_code == 200
    assert current.json()["sha256"] == upload.json()["sha256"]


def test_delete_profile_key_removes_rows_and_object_files(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert upload_persistent(client, key, lease, b"first", now=base).status_code == 201
    assert upload_persistent(client, key, lease, b"second", now=base + timedelta(days=1)).status_code == 201

    with client.app.state.SessionLocal() as db:
        object_paths = list(
            db.scalars(select(PersistentVersion.object_path).where(PersistentVersion.profile_id == profile["id"]))
        )
    assert len(object_paths) == 2
    object_root = client.app.state.storage.root
    assert all((object_root / path).exists() for path in object_paths)

    client.post("/logout")
    login(client, "admin@example.com")
    assert client.post(f"/admin/profile-keys/{profile['id']}/ban", json={"reason": "delete me"}).status_code == 200
    client.post("/logout")
    login(client)

    deleted = client.delete(f"/account/profile-keys/{profile['id']}")

    assert deleted.status_code == 204
    assert client.get("/v1/profile/resolve", headers={"X-MAS-Profile-Key": key}).status_code == 401
    assert client.get("/account/profile-keys").json()["items"] == []
    assert client.get(f"/account/profiles/{profile['id']}").status_code == 404

    client.post("/logout")
    login(client, "admin@example.com")
    assert client.get(f"/admin/profiles/{profile['id']}").status_code == 404

    with client.app.state.SessionLocal() as db:
        assert db.get(Profile, profile["id"]) is None
        assert db.scalar(select(Lock).where(Lock.profile_id == profile["id"])) is None
        assert db.scalar(select(PersistentCurrent).where(PersistentCurrent.profile_id == profile["id"])) is None
        assert db.scalars(select(PersistentDailyBackup).where(PersistentDailyBackup.profile_id == profile["id"])).all() == []
        assert db.scalars(select(PersistentVersion).where(PersistentVersion.profile_id == profile["id"])).all() == []
        assert db.scalars(select(Ban).where(Ban.target_type == "key", Ban.target_id == profile["id"], Ban.revoked_at.is_(None))).all() == []
        actions = [log.action for log in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert "profile_key.delete" in actions
    assert all(not (object_root / path).exists() for path in object_paths)


def test_lock_acquire_heartbeat_release_and_ttl_expiry(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    first = acquire_lock(client, key)

    conflict = client.post("/v1/locks/acquire", headers={"X-MAS-Profile-Key": key})
    assert conflict.status_code == 409

    heartbeat = client.post(
        "/v1/locks/heartbeat",
        headers={"X-MAS-Profile-Key": key, "X-MAS-Lease-Token": first},
    )
    assert heartbeat.status_code == 200

    released = client.post(
        "/v1/locks/release",
        headers={"X-MAS-Profile-Key": key, "X-MAS-Lease-Token": first},
    )
    assert released.status_code == 204
    second = acquire_lock(client, key)

    future = (datetime.now(timezone.utc) + timedelta(seconds=61)).isoformat()
    expired_reacquire = client.post(
        "/v1/locks/acquire",
        headers={"X-MAS-Profile-Key": key, "X-Test-Now": future},
    )
    assert expired_reacquire.status_code == 200
    assert expired_reacquire.json()["lease_token"] != second


def test_upload_requires_valid_lease_and_downloads_current_bytes(client):
    profile = new_profile(client)
    key = profile["profile_key"]

    no_lease = upload_persistent(client, key, "wrong", b"cloud-v1")
    assert no_lease.status_code == 409

    lease = acquire_lock(client, key)
    uploaded = upload_persistent(client, key, lease, b"cloud-v1")
    assert uploaded.status_code == 201
    assert uploaded.json()["size"] == len(b"cloud-v1")

    current = client.get("/v1/persistent/current", headers={"X-MAS-Profile-Key": key})
    assert current.json()["sha256"] == uploaded.json()["sha256"]

    downloaded = client.get("/v1/persistent/download", headers={"X-MAS-Profile-Key": key})
    assert downloaded.status_code == 200
    assert downloaded.content == b"cloud-v1"


def test_daily_backups_replace_same_day_and_retain_latest_ten_days(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    assert upload_persistent(client, key, lease, b"day-1-a", now=base).status_code == 201
    assert upload_persistent(client, key, lease, b"day-1-b", now=base + timedelta(hours=2)).status_code == 201
    backups = client.get("/v1/persistent/backups", headers={"X-MAS-Profile-Key": key}).json()["items"]
    assert len(backups) == 1
    assert backups[0]["backup_date"] == "2026-01-01"

    for day in range(1, 11):
        response = upload_persistent(
            client,
            key,
            lease,
            f"day-{day + 1}".encode(),
            now=base + timedelta(days=day),
        )
        assert response.status_code == 201

    backups = client.get("/v1/persistent/backups", headers={"X-MAS-Profile-Key": key}).json()["items"]
    assert len(backups) == 10
    assert [item["backup_date"] for item in backups][0] == "2026-01-11"
    assert [item["backup_date"] for item in backups][-1] == "2026-01-02"


def test_account_profile_detail_exposes_owned_persistent_files(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    first = upload_persistent(client, key, lease, b"first", now=base)
    assert first.status_code == 201
    second = upload_persistent(client, key, lease, b"second", now=base + timedelta(days=1))
    assert second.status_code == 201

    detail = client.get(f"/account/profiles/{profile['id']}")
    assert detail.status_code == 200
    assert detail.json()["profile"]["id"] == profile["id"]
    assert detail.json()["profile"]["storage_usage"] == len(b"second")

    current = client.get(f"/account/profiles/{profile['id']}/persistent/current")
    assert current.status_code == 200
    assert current.json()["sha256"] == second.json()["sha256"]

    downloaded = client.get(f"/account/profiles/{profile['id']}/persistent/current/download")
    assert downloaded.status_code == 200
    assert downloaded.content == b"second"

    backups = client.get(f"/account/profiles/{profile['id']}/persistent/backups")
    assert backups.status_code == 200
    items = backups.json()["items"]
    assert [item["backup_date"] for item in items] == ["2026-01-02", "2026-01-01"]
    assert items[0]["sha256"] == second.json()["sha256"]

    backup_download = client.get(f"/account/profiles/{profile['id']}/persistent/backups/{items[-1]['id']}/download")
    assert backup_download.status_code == 200
    assert backup_download.content == b"first"


def test_admin_profile_detail_lists_persistent_backups(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = upload_persistent(client, key, lease, b"first", now=base)
    assert first.status_code == 201
    second = upload_persistent(client, key, lease, b"second", now=base + timedelta(days=1))
    assert second.status_code == 201

    client.post("/logout")
    login(client, "admin@example.com")

    detail = client.get(f"/admin/profiles/{profile['id']}")
    assert detail.status_code == 200
    assert detail.json()["profile"]["storage_usage"] == len(b"second")

    current = client.get(f"/admin/profiles/{profile['id']}/persistent/current")
    assert current.status_code == 200
    assert current.json()["sha256"] == second.json()["sha256"]

    backups = client.get(f"/admin/profiles/{profile['id']}/persistent/backups")

    assert backups.status_code == 200
    items = backups.json()["items"]
    assert [item["backup_date"] for item in items] == ["2026-01-02", "2026-01-01"]
    assert items[0]["sha256"] == second.json()["sha256"]


def test_admin_profile_current_returns_no_current_code(client):
    profile = new_profile(client)
    client.post("/logout")
    login(client, "admin@example.com")

    current = client.get(f"/admin/profiles/{profile['id']}/persistent/current")

    assert current.status_code == 404
    assert current.json()["detail"]["code"] == "no_current_persistent"


def test_account_profile_detail_rejects_profiles_owned_by_other_users(client):
    login(client, "admin@example.com")
    profile = client.post("/account/profile-keys", json={"display_name": "Admin profile"}).json()
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert upload_persistent(client, key, lease, b"admin-first", now=base).status_code == 201
    assert upload_persistent(client, key, lease, b"admin-second", now=base + timedelta(days=1)).status_code == 201
    backups = client.get(f"/account/profiles/{profile['id']}/persistent/backups").json()["items"]

    client.post("/logout")
    login(client, "user@example.com")

    urls = [
        f"/account/profiles/{profile['id']}",
        f"/account/profiles/{profile['id']}/persistent/current",
        f"/account/profiles/{profile['id']}/persistent/current/download",
        f"/account/profiles/{profile['id']}/persistent/backups",
        f"/account/profiles/{profile['id']}/persistent/backups/{backups[0]['id']}/download",
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "profile_not_found"


def test_user_and_admin_backup_restore_update_current(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert upload_persistent(client, key, lease, b"first", now=base).status_code == 201
    assert upload_persistent(client, key, lease, b"second", now=base + timedelta(days=1)).status_code == 201

    backups = client.get("/v1/persistent/backups", headers={"X-MAS-Profile-Key": key}).json()["items"]
    oldest = backups[-1]["id"]
    restored = client.post(f"/v1/persistent/backups/{oldest}/restore", headers={"X-MAS-Profile-Key": key})
    assert restored.status_code == 200
    assert client.get("/v1/persistent/download", headers={"X-MAS-Profile-Key": key}).content == b"first"

    client.post("/logout")
    login(client, "admin@example.com")
    newest = backups[0]["id"]
    admin_restore = client.post(f"/admin/profiles/{profile['id']}/persistent/backups/{newest}/restore")
    assert admin_restore.status_code == 200
    admin_download = client.get(f"/admin/profiles/{profile['id']}/persistent/current/download")
    assert admin_download.content == b"second"


def test_bans_block_submod_operations_with_machine_readable_detail(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    client.post("/logout")
    login(client, "admin@example.com")

    banned = client.post(f"/admin/profiles/{profile['id']}/ban", json={"reason": "testing"})
    assert banned.status_code == 200

    response = client.get("/v1/profile/resolve", headers={"X-MAS-Profile-Key": key})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "banned"
    assert client.post("/v1/locks/acquire", headers={"X-MAS-Profile-Key": key}).json()["detail"]["code"] == "banned"


def test_key_and_user_bans_block_submod_operations(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    user_id = login(client)["user"]["id"]
    client.post("/logout")
    login(client, "admin@example.com")

    assert client.post(f"/admin/profile-keys/{profile['id']}/ban", json={"reason": "key"}).status_code == 200
    assert client.get("/v1/profile/resolve", headers={"X-MAS-Profile-Key": key}).status_code == 403

    assert client.post(f"/admin/profile-keys/{profile['id']}/unban").status_code == 200
    assert client.post(f"/admin/users/{user_id}/ban", json={"reason": "user"}).status_code == 200
    assert client.get("/v1/profile/resolve", headers={"X-MAS-Profile-Key": key}).status_code == 403


def test_admin_actions_write_audit_logs_with_request_context(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    assert upload_persistent(client, key, lease, b"audit").status_code == 201
    backups = client.get("/v1/persistent/backups", headers={"X-MAS-Profile-Key": key}).json()["items"]

    client.post("/logout")
    admin = login(client, "admin@example.com")
    headers = {"User-Agent": "pytest-agent"}

    assert client.get(f"/admin/users/{admin['user']['id']}", headers=headers).status_code == 200
    assert client.get(f"/admin/profiles/{profile['id']}/persistent/current/download", headers=headers).status_code == 200
    assert client.get(
        f"/admin/profiles/{profile['id']}/persistent/backups/{backups[0]['id']}/download",
        headers=headers,
    ).status_code == 200
    assert client.post(f"/admin/profiles/{profile['id']}/ban", json={"reason": "audit"}, headers=headers).status_code == 200
    assert client.post(f"/admin/locks/{profile['id']}/release", headers=headers).status_code == 204

    logs = client.get("/admin/audit-logs").json()["items"]
    actions = {entry["action"] for entry in logs}
    assert "admin.user.view" in actions
    assert "admin.persistent.current.download" in actions
    assert "admin.persistent.backup.download" in actions
    assert "admin.profile.ban" in actions
    assert "admin.lock.release" in actions
    assert any(entry["user_agent"] == "pytest-agent" for entry in logs)


def test_admin_delete_profile_key_removes_profile_and_writes_audit_log(client):
    profile = new_profile(client)
    client.post("/logout")
    login(client, "admin@example.com")

    response = client.delete(f"/admin/profile-keys/{profile['id']}", headers={"User-Agent": "pytest-agent"})

    assert response.status_code == 204
    assert client.get(f"/admin/profiles/{profile['id']}").status_code == 404
    logs = client.get("/admin/audit-logs").json()["items"]
    delete_log = next(entry for entry in logs if entry["action"] == "admin.profile_key.delete")
    assert delete_log["target_user_id"] == profile["user_id"]
    assert delete_log["target_profile_id"] == profile["id"]
    assert delete_log["target_profile_key_id"] == profile["id"]
    assert delete_log["user_agent"] == "pytest-agent"


def test_admin_user_detail_includes_only_target_users_profiles_sorted_by_id(client):
    first = new_profile(client)
    second = client.post("/account/profile-keys", json={"display_name": "Alt"}).json()

    client.post("/logout")
    login(client, "admin@example.com")
    admin_profile = client.post("/account/profile-keys", json={"display_name": "Admin profile"}).json()

    client.post("/logout")
    normal_user = login(client, "user@example.com")["user"]
    client.post("/logout")
    login(client, "admin@example.com")

    response = client.get(f"/admin/users/{normal_user['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["id"] == normal_user["id"]
    profile_ids = [profile["id"] for profile in payload["profiles"]]
    assert profile_ids == sorted([first["id"], second["id"]])
    assert admin_profile["id"] not in profile_ids
    assert payload["profiles"][0]["user_id"] == normal_user["id"]
    assert payload["profiles"][0]["display_name"] == "Main"
    assert payload["profiles"][0]["profile_key"] == first["profile_key"]


def test_admin_user_list_includes_profile_count_storage_last_upload_and_lock_status(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    assert upload_persistent(client, key, lease, b"usage").status_code == 201

    client.post("/logout")
    login(client, "admin@example.com")
    users = client.get("/admin/users").json()["items"]
    normal = next(user for user in users if user["username"] == "normal")

    assert normal["profile_count"] == 1
    assert normal["storage_usage"] == len(b"usage")
    assert normal["last_upload_at"] is not None
    assert normal["lock_status"] == "active"
