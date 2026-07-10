from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mas_unisync_server.main import create_app
from mas_unisync_server.models import AuditLog, Ban, Lock, PersistentCurrent, PersistentDailyBackup, PersistentVersion, Profile, StorageBucket, User
from mas_unisync_server import services as server_services
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


def make_client(tmp_path, *, trusted_proxy_ips: set[str] | None = None, client_host: str = "127.0.0.1"):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'server.db'}",
        object_storage_path=tmp_path / "objects",
        session_secret="test-secret",
        admin_flarum_group_ids={"1"},
        admin_flarum_group_names={"Admin"},
        lock_ttl_seconds=60,
        trusted_proxy_ips=trusted_proxy_ips or set(),
    )
    return TestClient(
        create_app(settings=settings, flarum_client=FakeFlarumClient()),
        client=(client_host, 50000),
    )


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


def new_guest_profile(client: TestClient, *, now: datetime | None = None):
    headers = {"X-Test-Now": now.isoformat()} if now else {}
    response = client.post("/v1/guest/profile-key", headers=headers)
    assert response.status_code == 201
    return response.json()


def test_guest_profile_key_creation_is_unique_and_audited(client):
    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    first = new_guest_profile(client, now=now)
    second = new_guest_profile(client, now=now)

    assert first["profile_key"].startswith("maspk_")
    assert first["profile_key"] != second["profile_key"]
    assert first["is_guest"] is True
    assert first["guest_retention_days"] == 360
    assert first["guest_expires_at"] == (now + timedelta(days=360)).isoformat()
    with client.app.state.SessionLocal() as db:
        guests = list(db.scalars(select(User).where(User.role == "guest").order_by(User.id)))
        profile_counts = [len(user.profiles) for user in guests]
        actions = [log.action for log in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert len(guests) == 2
    assert profile_counts == [1, 1]
    assert actions == ["guest.profile_key.create", "guest.profile_key.create"]


def test_guest_login_allows_read_only_archive_access(client):
    guest = new_guest_profile(client)

    login_response = client.post("/login/guest", json={"profile_key": guest["profile_key"]})

    assert login_response.status_code == 200
    assert login_response.json()["user"]["role"] == "guest"
    listed = client.get("/account/profile-keys")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [guest["id"]]
    assert client.get(f"/account/profiles/{guest['id']}").status_code == 200
    for response in (
        client.post("/account/profile-keys", json={"display_name": "Nope"}),
        client.post("/account/profile-keys/import-guest", json={"profile_key": guest["profile_key"]}),
        client.post(f"/account/profile-keys/{guest['id']}/refresh"),
        client.delete(f"/account/profile-keys/{guest['id']}"),
    ):
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "guest_account_read_only"


def test_guest_login_rejects_normal_invalid_and_banned_keys(client):
    normal = new_profile(client)
    client.post("/logout")

    normal_login = client.post("/login/guest", json={"profile_key": normal["profile_key"]})
    invalid_login = client.post("/login/guest", json={"profile_key": "maspk_missing"})
    guest = new_guest_profile(client)
    with client.app.state.SessionLocal() as db:
        db.add(Ban(target_type="key", target_id=guest["id"], reason="blocked"))
        db.commit()
    banned_login = client.post("/login/guest", json={"profile_key": guest["profile_key"]})

    assert normal_login.status_code == 403
    assert normal_login.json()["detail"]["code"] == "profile_key_not_guest"
    assert invalid_login.status_code == 401
    assert invalid_login.json()["detail"]["code"] == "invalid_profile_key"
    assert banned_login.status_code == 403
    assert banned_login.json()["detail"]["code"] == "banned"


def test_guest_session_can_release_lock_download_and_restore_its_archive(client):
    guest = new_guest_profile(client)
    key = guest["profile_key"]
    lease = acquire_lock(client, key)
    base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert upload_persistent(client, key, lease, b"first", now=base).status_code == 201
    assert upload_persistent(client, key, lease, b"second", now=base + timedelta(days=1)).status_code == 201
    backups = client.get("/v1/persistent/backups", headers={"X-MAS-Profile-Key": key}).json()["items"]

    assert client.post("/login/guest", json={"profile_key": key}).status_code == 200
    assert client.post(f"/account/profiles/{guest['id']}/lock/release").status_code == 204
    current = client.get(f"/account/profiles/{guest['id']}/persistent/current/download")
    assert current.content == b"second"
    restored = client.post(
        f"/account/profiles/{guest['id']}/persistent/backups/{backups[-1]['id']}/restore"
    )
    assert restored.status_code == 200
    assert client.get(f"/account/profiles/{guest['id']}/persistent/current/download").content == b"first"


def test_import_guest_profile_preserves_key_archive_lock_and_objects(client):
    guest = new_guest_profile(client)
    key = guest["profile_key"]
    lease = acquire_lock(client, key)
    base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert upload_persistent(client, key, lease, b"first", now=base).status_code == 201
    assert upload_persistent(client, key, lease, b"second", now=base + timedelta(days=1)).status_code == 201
    with client.app.state.SessionLocal() as db:
        old_owner_id = db.get(Profile, guest["id"]).user_id
        old_lock_id = db.scalar(select(Lock.id).where(Lock.profile_id == guest["id"]))
        old_version_ids = list(db.scalars(select(PersistentVersion.id).where(PersistentVersion.profile_id == guest["id"]).order_by(PersistentVersion.id)))
        old_backup_ids = list(db.scalars(select(PersistentDailyBackup.id).where(PersistentDailyBackup.profile_id == guest["id"]).order_by(PersistentDailyBackup.id)))
        object_paths = list(db.scalars(select(PersistentVersion.object_path).where(PersistentVersion.profile_id == guest["id"])))

    assert client.post("/login/guest", json={"profile_key": key}).status_code == 200
    backups = client.get(f"/account/profiles/{guest['id']}/persistent/backups").json()["items"]
    assert client.post(
        f"/account/profiles/{guest['id']}/persistent/backups/{backups[-1]['id']}/restore"
    ).status_code == 200

    owner = login(client)["user"]
    imported = client.post("/account/profile-keys/import-guest", json={"profile_key": key})

    assert imported.status_code == 200
    assert imported.json()["profile_key"] == key
    assert imported.json()["is_guest"] is False
    with client.app.state.SessionLocal() as db:
        profile = db.get(Profile, guest["id"])
        assert profile.user_id == owner["id"]
        assert db.get(User, old_owner_id) is None
        assert db.scalar(select(Lock.id).where(Lock.profile_id == guest["id"])) == old_lock_id
        assert list(db.scalars(select(PersistentVersion.id).where(PersistentVersion.profile_id == guest["id"]).order_by(PersistentVersion.id))) == old_version_ids
        assert list(db.scalars(select(PersistentDailyBackup.id).where(PersistentDailyBackup.profile_id == guest["id"]).order_by(PersistentDailyBackup.id))) == old_backup_ids
        guest_audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "persistent.backup.restore")
        )
        assert guest_audit.actor_user_id is None
        assert guest_audit.actor_role == "guest"
        actions = [log.action for log in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert all((client.app.state.storage.root / path).exists() for path in object_paths)
    assert "guest.profile_key.import" in actions


def test_import_guest_profile_reports_invalid_normal_claimed_and_quota_errors(client):
    normal = new_profile(client)
    guest = new_guest_profile(client)
    imported = client.post("/account/profile-keys/import-guest", json={"profile_key": guest["profile_key"]})
    assert imported.status_code == 200

    invalid = client.post("/account/profile-keys/import-guest", json={"profile_key": "maspk_missing"})
    normal_key = client.post("/account/profile-keys/import-guest", json={"profile_key": normal["profile_key"]})
    claimed = client.post("/account/profile-keys/import-guest", json={"profile_key": guest["profile_key"]})

    assert invalid.status_code == 404
    assert invalid.json()["detail"]["code"] == "invalid_profile_key"
    assert normal_key.status_code == 409
    assert normal_key.json()["detail"]["code"] == "profile_key_not_guest"
    assert claimed.status_code == 409
    assert claimed.json()["detail"]["code"] == "guest_profile_already_claimed"

    client.post("/logout")
    login(client, "admin@example.com")
    settings = client.get("/admin/settings").json()["settings"]
    settings["max_active_profiles_per_account"] = 1
    assert client.put("/admin/settings", json=settings).status_code == 200
    client.post("/logout")
    login(client)
    quota_guest = new_guest_profile(client)
    quota = client.post("/account/profile-keys/import-guest", json={"profile_key": quota_guest["profile_key"]})
    assert quota.status_code == 409
    assert quota.json()["detail"]["code"] == "active_profile_limit_exceeded"
    with client.app.state.SessionLocal() as db:
        quota_profile = db.get(Profile, quota_guest["id"])
        assert quota_profile.user.role == "guest"


def test_admin_user_list_includes_admin_normal_and_guest_users(client):
    guest = new_guest_profile(client)
    client.post("/logout")
    login(client)
    login(client, "admin@example.com")

    users = client.get("/admin/users")

    assert users.status_code == 200
    payload = users.json()
    roles = {user["role"] for user in payload["items"]}
    ids = {user["id"] for user in payload["items"]}
    assert {"admin", "user", "guest"} <= roles
    assert guest["user_id"] in ids
    assert payload["page"] == 1
    assert payload["page_size"] == 25
    assert payload["has_next"] is False


def test_admin_user_list_paginates_with_allowed_page_sizes_and_has_next(client):
    login(client, "admin@example.com")
    with client.app.state.SessionLocal() as db:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for index in range(30):
            db.add(
                User(
                    flarum_user_id=f"bulk:{index}",
                    username=f"bulk-{index:02d}",
                    display_name=f"Bulk {index:02d}",
                    role="user",
                    flarum_groups_json="[]",
                    created_at=now,
                    updated_at=now,
                )
            )
        db.commit()

    first = client.get("/admin/users?page=1&page_size=25")
    second = client.get("/admin/users?page=2&page_size=25")
    hundred = client.get("/admin/users?page_size=100")
    invalid = client.get("/admin/users?page_size=26")

    assert first.status_code == 200
    assert len(first.json()["items"]) == 25
    assert first.json()["has_next"] is True
    assert second.status_code == 200
    assert len(second.json()["items"]) == 6
    assert second.json()["page"] == 2
    assert second.json()["has_next"] is False
    assert hundred.status_code == 200
    assert hundred.json()["page_size"] == 100
    assert invalid.status_code == 422


def test_admin_user_list_search_sorts_and_filters_by_last_upload_window(client):
    early_profile = new_profile(client)
    early_key = early_profile["profile_key"]
    early_lease = acquire_lock(client, early_key)
    assert upload_persistent(
        client,
        early_key,
        early_lease,
        b"early",
        now=datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),
    ).status_code == 201

    client.post("/logout")
    late_guest = new_guest_profile(client)
    late_lease = acquire_lock(client, late_guest["profile_key"])
    assert upload_persistent(
        client,
        late_guest["profile_key"],
        late_lease,
        b"late",
        now=datetime(2026, 2, 5, 10, 0, tzinfo=timezone.utc),
    ).status_code == 201

    client.post("/logout")
    login(client, "admin@example.com")

    guest_search = client.get("/admin/users?q=guest")
    id_desc = client.get("/admin/users?sort=id&order=desc")
    upload_desc = client.get("/admin/users?sort=last_upload_at&order=desc")
    upload_window = client.get(
        "/admin/users"
        "?last_upload_from=2026-02-01"
        "&last_upload_to=2026-02-05"
    )

    assert guest_search.status_code == 200
    assert any(user["role"] == "guest" for user in guest_search.json()["items"])
    assert [user["id"] for user in id_desc.json()["items"]] == sorted(
        [user["id"] for user in id_desc.json()["items"]],
        reverse=True,
    )
    assert upload_desc.json()["items"][0]["id"] == late_guest["user_id"]
    assert [user["id"] for user in upload_window.json()["items"]] == [late_guest["user_id"]]


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

    first_upload = upload_persistent(client, key, lease, b"day-1-a", now=base)
    assert first_upload.status_code == 201
    with client.app.state.SessionLocal() as db:
        first_object_path = db.scalar(
            select(PersistentVersion.object_path).where(PersistentVersion.profile_id == profile["id"])
        )
    object_root = client.app.state.storage.root
    assert (object_root / first_object_path).exists()

    second_upload = upload_persistent(client, key, lease, b"day-1-b", now=base + timedelta(hours=2))
    assert second_upload.status_code == 201
    backups = client.get("/v1/persistent/backups", headers={"X-MAS-Profile-Key": key}).json()["items"]
    assert len(backups) == 1
    assert backups[0]["backup_date"] == "2026-01-01"
    assert second_upload.json()["id"] == first_upload.json()["id"]

    with client.app.state.SessionLocal() as db:
        versions = list(
            db.scalars(select(PersistentVersion).where(PersistentVersion.profile_id == profile["id"]))
        )
        backup_rows = list(
            db.scalars(select(PersistentDailyBackup).where(PersistentDailyBackup.profile_id == profile["id"]))
        )
        current = db.scalar(select(PersistentCurrent).where(PersistentCurrent.profile_id == profile["id"]))
    assert len(versions) == 1
    assert len(backup_rows) == 1
    assert current.version_id == versions[0].id == backup_rows[0].version_id
    assert versions[0].sha256 == second_upload.json()["sha256"]
    assert not (object_root / first_object_path).exists()
    assert (object_root / versions[0].object_path).exists()
    assert list((object_root / str(profile["id"])).rglob("*.bin")) == [object_root / versions[0].object_path]

    current_download = client.get("/v1/persistent/download", headers={"X-MAS-Profile-Key": key})
    assert current_download.status_code == 200
    assert current_download.content == b"day-1-b"
    backup_download = client.get(
        f"/account/profiles/{profile['id']}/persistent/backups/{backups[0]['id']}/download"
    )
    assert backup_download.status_code == 200
    assert backup_download.content == b"day-1-b"

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
    assert detail.json()["profile"]["storage_usage"] == len(b"first") + len(b"second")

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

    restored = client.post(f"/account/profiles/{profile['id']}/persistent/backups/{items[-1]['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["sha256"] == first.json()["sha256"]
    restored_download = client.get(f"/account/profiles/{profile['id']}/persistent/current/download")
    assert restored_download.content == b"first"


def test_account_profile_detail_reports_current_lock_status(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    acquire_lock(client, key)

    detail = client.get(f"/account/profiles/{profile['id']}")

    assert detail.status_code == 200
    assert detail.json()["profile"]["lock_status"] == "active"

    future = (datetime.now(timezone.utc) + timedelta(seconds=61)).isoformat()
    expired_detail = client.get(f"/account/profiles/{profile['id']}", headers={"X-Test-Now": future})

    assert expired_detail.status_code == 200
    assert expired_detail.json()["profile"]["lock_status"] == "none"


def test_account_profile_lock_release_deletes_owned_lock_and_is_idempotent(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    acquire_lock(client, key)

    released = client.post(f"/account/profiles/{profile['id']}/lock/release")

    assert released.status_code == 204
    assert client.get(f"/account/profiles/{profile['id']}").json()["profile"]["lock_status"] == "none"

    second_release = client.post(f"/account/profiles/{profile['id']}/lock/release")

    assert second_release.status_code == 204
    assert client.post("/v1/locks/acquire", headers={"X-MAS-Profile-Key": key}).status_code == 200
    with client.app.state.SessionLocal() as db:
        actions = [log.action for log in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert "profile.lock.release" in actions


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
    assert detail.json()["profile"]["storage_usage"] == len(b"first") + len(b"second")

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

    released = client.post(f"/account/profiles/{profile['id']}/lock/release")
    assert released.status_code == 404
    assert released.json()["detail"]["code"] == "profile_not_found"


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


def test_admin_audit_logs_paginate_search_and_keep_fixed_desc_order(client):
    login(client, "admin@example.com")
    with client.app.state.SessionLocal() as db:
        base = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
        for index in range(30):
            db.add(
                AuditLog(
                    actor_role="admin",
                    action=f"bulk.audit.{index:02d}",
                    created_at=base + timedelta(minutes=index),
                    target_user_id=index,
                )
            )
        db.commit()

    first = client.get("/admin/audit-logs?page=1&page_size=25")
    second = client.get("/admin/audit-logs?page=2&page_size=25")
    searched = client.get("/admin/audit-logs?q=bulk.audit.29")
    invalid = client.get("/admin/audit-logs?page_size=200")

    assert first.status_code == 200
    assert len(first.json()["items"]) == 25
    assert first.json()["has_next"] is True
    first_ids = [entry["id"] for entry in first.json()["items"]]
    assert first_ids == sorted(first_ids, reverse=True)
    assert second.status_code == 200
    assert len(second.json()["items"]) == 5
    assert second.json()["page"] == 2
    assert second.json()["has_next"] is False
    assert [entry["action"] for entry in searched.json()["items"]] == ["bulk.audit.29"]
    assert invalid.status_code == 422


def test_admin_settings_default_from_origin_save_and_audit(client):
    login(client, "admin@example.com")

    defaults = client.get("/admin/settings", headers={"User-Agent": "pytest-agent"})

    assert defaults.status_code == 200
    default_settings = defaults.json()["settings"]
    assert default_settings == {
        "backend_api_url": "http://testserver",
        "frontend_web_url": "http://testserver",
        "profile_storage_limit_bytes": 10 * 1024 * 1024,
        "max_active_profiles_per_account": 3,
        "guest_key_retention_days": 360,
        "active_storage_bucket_id": default_settings["storage_buckets"][0]["id"],
        "storage_buckets": [
            {
                "id": default_settings["storage_buckets"][0]["id"],
                "name": "Docker local storage",
                "type": "local",
                "is_active": True,
                "space_budget_bytes": None,
                "usage_summary": {
                    "file_count": 0,
                    "total_size": 0,
                    "backup_reference_count": 0,
                    "current_reference_count": 0,
                },
                "is_config_locked": False,
                "config": {"path": str(client.app.state.settings.object_storage_path)},
            }
        ],
    }

    saved = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "https://api.example.test/base/",
            "frontend_web_url": "https://portal.example.test",
            "profile_storage_limit_bytes": 12345,
            "max_active_profiles_per_account": 7,
            "guest_key_retention_days": 45,
        },
        headers={"User-Agent": "settings-agent"},
    )

    assert saved.status_code == 200
    saved_settings = saved.json()["settings"]
    assert saved_settings == {
        "backend_api_url": "https://api.example.test/base",
        "frontend_web_url": "https://portal.example.test",
        "profile_storage_limit_bytes": 12345,
        "max_active_profiles_per_account": 7,
        "guest_key_retention_days": 45,
        "active_storage_bucket_id": default_settings["storage_buckets"][0]["id"],
        "storage_buckets": default_settings["storage_buckets"],
    }
    assert client.get("/admin/settings").json()["settings"]["backend_api_url"] == "https://api.example.test/base"

    logs = client.get("/admin/audit-logs").json()["items"]
    settings_log = next(entry for entry in logs if entry["action"] == "admin.settings.update")
    assert settings_log["user_agent"] == "settings-agent"


def write_settings_audit_log(client: TestClient, *, x_forwarded_for: str | None = None):
    login(client, "admin@example.com")
    headers = {}
    if x_forwarded_for is not None:
        headers["X-Forwarded-For"] = x_forwarded_for
    response = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "https://api.example.test/base/",
            "frontend_web_url": "https://portal.example.test",
            "profile_storage_limit_bytes": 12345,
            "max_active_profiles_per_account": 7,
        },
        headers=headers,
    )
    assert response.status_code == 200
    logs = client.get("/admin/audit-logs").json()["items"]
    return next(entry for entry in logs if entry["action"] == "admin.settings.update")


def test_audit_log_uses_x_forwarded_for_from_trusted_proxy(tmp_path):
    with make_client(tmp_path, trusted_proxy_ips={"127.0.0.1"}) as client:
        settings_log = write_settings_audit_log(client, x_forwarded_for="203.0.113.10")

    assert settings_log["ip_address"] == "203.0.113.10"


def test_audit_log_uses_first_x_forwarded_for_address_from_trusted_proxy(tmp_path):
    with make_client(tmp_path, trusted_proxy_ips={"127.0.0.0/24"}) as client:
        settings_log = write_settings_audit_log(client, x_forwarded_for="203.0.113.10, 10.0.0.1")

    assert settings_log["ip_address"] == "203.0.113.10"


def test_audit_log_ignores_x_forwarded_for_from_untrusted_client(tmp_path):
    with make_client(tmp_path, trusted_proxy_ips={"10.0.0.0/8"}, client_host="198.51.100.25") as client:
        settings_log = write_settings_audit_log(client, x_forwarded_for="203.0.113.10")

    assert settings_log["ip_address"] == "198.51.100.25"


def test_audit_log_falls_back_to_direct_client_without_x_forwarded_for(tmp_path):
    with make_client(tmp_path, trusted_proxy_ips={"127.0.0.1"}) as client:
        settings_log = write_settings_audit_log(client)

    assert settings_log["ip_address"] == "127.0.0.1"


def test_admin_settings_reject_non_admin_and_invalid_values(client):
    login(client)

    assert client.get("/admin/settings").status_code == 403
    assert client.put(
        "/admin/settings",
        json={
            "backend_api_url": "https://api.example.test",
            "frontend_web_url": "https://portal.example.test",
            "profile_storage_limit_bytes": 1,
            "max_active_profiles_per_account": 1,
        },
    ).status_code == 403

    client.post("/logout")
    login(client, "admin@example.com")
    invalid = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 0,
            "max_active_profiles_per_account": 0,
        },
    )

    assert invalid.status_code == 422

    invalid_guest_retention = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 1,
            "max_active_profiles_per_account": 1,
            "guest_key_retention_days": 0,
        },
    )
    assert invalid_guest_retention.status_code == 422


def test_guest_cleanup_uses_last_activity_and_does_not_touch_normal_profiles(client):
    cleanup = getattr(server_services, "cleanup_expired_guest_profiles", None)
    assert callable(cleanup)
    now = datetime(2026, 12, 31, 10, 0, tzinfo=timezone.utc)
    expired = new_guest_profile(client)
    recent = new_guest_profile(client)
    normal = new_profile(client)
    lease = acquire_lock(client, expired["profile_key"])
    assert upload_persistent(client, expired["profile_key"], lease, b"expired-cloud").status_code == 201

    with client.app.state.SessionLocal() as db:
        expired_profile = db.get(Profile, expired["id"])
        expired_profile.created_at = now - timedelta(days=361)
        expired_profile.last_used_at = None
        recent_profile = db.get(Profile, recent["id"])
        recent_profile.created_at = now - timedelta(days=500)
        recent_profile.last_used_at = now - timedelta(days=30)
        normal_profile = db.get(Profile, normal["id"])
        normal_profile.created_at = now - timedelta(days=500)
        normal_profile.last_used_at = None
        db.add(
            AuditLog(
                actor_user_id=expired_profile.user_id,
                actor_role="guest",
                action="guest.test.action",
                target_profile_id=expired_profile.id,
                created_at=now - timedelta(days=361),
            )
        )
        object_path = db.scalar(
            select(PersistentVersion.object_path).where(PersistentVersion.profile_id == expired["id"])
        )
        db.commit()

    with client.app.state.SessionLocal() as db:
        result = cleanup(db, client.app.state.settings, now)

    assert result == {"deleted": 1, "storage_failures": 0}
    assert not (client.app.state.storage.root / object_path).exists()
    with client.app.state.SessionLocal() as db:
        assert db.get(Profile, expired["id"]) is None
        assert db.get(Profile, recent["id"]) is not None
        assert db.get(Profile, normal["id"]) is not None
        assert db.scalar(select(Lock).where(Lock.profile_id == expired["id"])) is None
        assert db.scalars(select(PersistentVersion).where(PersistentVersion.profile_id == expired["id"])).all() == []
        guest_audit = db.scalar(select(AuditLog).where(AuditLog.action == "guest.test.action"))
        assert guest_audit.actor_user_id is None
        assert guest_audit.actor_role == "guest"
        actions = [log.action for log in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert "system.guest_profile.cleanup" in actions


def test_guest_cleanup_keeps_database_rows_when_storage_delete_fails_and_retries(client, monkeypatch):
    cleanup = getattr(server_services, "cleanup_expired_guest_profiles", None)
    assert callable(cleanup)
    now = datetime(2026, 12, 31, 10, 0, tzinfo=timezone.utc)
    guest = new_guest_profile(client)
    lease = acquire_lock(client, guest["profile_key"])
    assert upload_persistent(client, guest["profile_key"], lease, b"retry-cloud").status_code == 201
    with client.app.state.SessionLocal() as db:
        profile = db.get(Profile, guest["id"])
        profile.created_at = now - timedelta(days=361)
        profile.last_used_at = None
        db.commit()

    original_delete = server_services.delete_version_object

    def fail_delete(*args, **kwargs):
        raise OSError("storage unavailable")

    monkeypatch.setattr(server_services, "delete_version_object", fail_delete)
    with client.app.state.SessionLocal() as db:
        failed = cleanup(db, client.app.state.settings, now)
    assert failed == {"deleted": 0, "storage_failures": 1}
    with client.app.state.SessionLocal() as db:
        assert db.get(Profile, guest["id"]) is not None
        assert db.scalar(select(Lock).where(Lock.profile_id == guest["id"])) is not None
        assert db.scalars(select(PersistentVersion).where(PersistentVersion.profile_id == guest["id"])).all()
        actions = [log.action for log in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert "system.guest_profile.cleanup_storage_failed" in actions

    monkeypatch.setattr(server_services, "delete_version_object", original_delete)
    with client.app.state.SessionLocal() as db:
        retried = cleanup(db, client.app.state.settings, now)
    assert retried == {"deleted": 1, "storage_failures": 0}
    with client.app.state.SessionLocal() as db:
        assert db.get(Profile, guest["id"]) is None


def test_guest_cleanup_uses_admin_configured_retention_days(client):
    cleanup = server_services.cleanup_expired_guest_profiles
    login(client, "admin@example.com")
    settings_payload = client.get("/admin/settings").json()["settings"]
    settings_payload["guest_key_retention_days"] = 30
    assert client.put("/admin/settings", json=settings_payload).status_code == 200
    client.post("/logout")
    created_at = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    guest = new_guest_profile(client, now=created_at)

    with client.app.state.SessionLocal() as db:
        result = cleanup(db, client.app.state.settings, created_at + timedelta(days=31))

    assert result == {"deleted": 1, "storage_failures": 0}
    with client.app.state.SessionLocal() as db:
        assert db.get(Profile, guest["id"]) is None


def test_app_startup_runs_guest_cleanup_once(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'startup.db'}",
        object_storage_path=tmp_path / "startup-objects",
        session_secret="test-secret",
    )
    app = create_app(settings=settings, flarum_client=FakeFlarumClient())
    old = datetime.now(timezone.utc) - timedelta(days=361)
    with app.state.SessionLocal() as db:
        user = User(
            flarum_user_id="guest:startup",
            username="guest-startup",
            role="guest",
            flarum_groups_json="[]",
            created_at=old,
            updated_at=old,
        )
        db.add(user)
        db.flush()
        profile = Profile(
            user_id=user.id,
            profile_key_plaintext="maspk_startup_expired",
            created_at=old,
            updated_at=old,
        )
        db.add(profile)
        db.commit()
        profile_id = profile.id

    with TestClient(app):
        pass

    with app.state.SessionLocal() as db:
        assert db.get(Profile, profile_id) is None


def test_admin_settings_manage_storage_buckets_and_active_local_uploads(client):
    login(client, "admin@example.com")
    settings = client.get("/admin/settings").json()["settings"]
    default_bucket = settings["storage_buckets"][0]
    secondary_root = client.app.state.settings.object_storage_path.parent / "secondary-objects"

    created = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 3,
            "storage_buckets": [
                default_bucket,
                {
                    "name": "Secondary local storage",
                    "type": "local",
                    "config": {"path": str(secondary_root)},
                },
            ],
        },
    )
    assert created.status_code == 200
    secondary_bucket = next(
        bucket for bucket in created.json()["settings"]["storage_buckets"] if bucket["name"] == "Secondary local storage"
    )

    activated = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 3,
            "active_storage_bucket_id": secondary_bucket["id"],
            "storage_buckets": created.json()["settings"]["storage_buckets"],
        },
    )
    assert activated.status_code == 200
    assert activated.json()["settings"]["active_storage_bucket_id"] == secondary_bucket["id"]

    client.post("/logout")
    profile = new_profile(client)
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    uploaded = upload_persistent(client, key, lease, b"secondary")

    assert uploaded.status_code == 201
    with client.app.state.SessionLocal() as db:
        version = db.scalar(select(PersistentVersion).where(PersistentVersion.profile_id == profile["id"]))
        assert version.bucket_id == secondary_bucket["id"]
        assert (secondary_root / version.object_path).exists()
        assert not (client.app.state.storage.root / version.object_path).exists()
    assert client.get("/v1/persistent/download", headers={"X-MAS-Profile-Key": key}).content == b"secondary"


def test_admin_can_test_storage_bucket_read_write_without_saving(client):
    login(client, "admin@example.com")
    test_root = client.app.state.settings.object_storage_path.parent / "probe-objects"

    response = client.post(
        "/admin/storage-buckets/test",
        json={
            "name": "Probe local storage",
            "type": "local",
            "config": {"path": str(test_root)},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert test_root.exists()
    assert list(test_root.rglob("*.bin")) == []


def test_admin_storage_bucket_test_reports_failure_phase(client, monkeypatch):
    login(client, "admin@example.com")

    class FailingStorage:
        def put(self, profile_id, version_id, sha256_hex, data):
            raise OSError("disk unavailable")

        def get(self, object_path):
            return b""

        def delete(self, object_path):
            pass

    monkeypatch.setattr("mas_unisync_server.services.storage_for_bucket", lambda bucket, settings: FailingStorage())

    response = client.post(
        "/admin/storage-buckets/test",
        json={
            "name": "Broken local storage",
            "type": "local",
            "config": {"path": str(client.app.state.settings.object_storage_path)},
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "storage_bucket_test_failed",
        "phase": "put",
        "error_type": "OSError",
    }


def test_legacy_versions_without_bucket_id_still_read_from_default_local_bucket(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    uploaded = upload_persistent(client, key, lease, b"legacy")
    assert uploaded.status_code == 201

    with client.app.state.SessionLocal() as db:
        version = db.scalar(select(PersistentVersion).where(PersistentVersion.profile_id == profile["id"]))
        version.bucket_id = None
        db.commit()

    assert client.get("/v1/persistent/download", headers={"X-MAS-Profile-Key": key}).content == b"legacy"


def test_admin_settings_masks_and_preserves_webdav_password(client):
    login(client, "admin@example.com")
    settings = client.get("/admin/settings").json()["settings"]
    default_bucket = settings["storage_buckets"][0]

    created = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 3,
            "storage_buckets": [
                default_bucket,
                {
                    "name": "WebDAV",
                    "type": "webdav",
                    "config": {
                        "base_url": "https://dav.example.test/root/",
                        "username": "mas",
                        "password": "secret",
                        "root_path": "persistent",
                    },
                },
            ],
        },
    )

    assert created.status_code == 200
    webdav = next(bucket for bucket in created.json()["settings"]["storage_buckets"] if bucket["type"] == "webdav")
    assert webdav["config"] == {
        "base_url": "https://dav.example.test/root",
        "username": "mas",
        "root_path": "persistent",
        "has_password": True,
    }

    preserved = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 3,
            "storage_buckets": [
                default_bucket,
                {
                    "id": webdav["id"],
                    "name": "WebDAV renamed",
                    "type": "webdav",
                    "config": {
                        "base_url": "https://dav.example.test/root/",
                        "username": "mas",
                        "password": "",
                        "root_path": "persistent",
                    },
                },
            ],
        },
    )

    assert preserved.status_code == 200
    with client.app.state.SessionLocal() as db:
        bucket = db.get(StorageBucket, webdav["id"])
        assert "secret" not in bucket.config_json
    webdav_after = next(bucket for bucket in preserved.json()["settings"]["storage_buckets"] if bucket["id"] == webdav["id"])
    assert webdav_after["name"] == "WebDAV renamed"
    assert webdav_after["config"]["has_password"] is True
    assert "password" not in webdav_after["config"]


def test_admin_settings_reports_legacy_plaintext_webdav_password_as_configured(client):
    login(client, "admin@example.com")
    with client.app.state.SessionLocal() as db:
        bucket = StorageBucket(
            name="Legacy WebDAV",
            type="webdav",
            is_active=False,
            config_json=(
                '{"base_url": "https://dav.example.test/root", "username": "mas", '
                '"password": "legacy-secret", "root_path": "persistent"}'
            ),
        )
        db.add(bucket)
        db.commit()

    settings = client.get("/admin/settings").json()["settings"]

    webdav = next(bucket for bucket in settings["storage_buckets"] if bucket["name"] == "Legacy WebDAV")
    assert webdav["config"]["has_password"] is True
    assert "password" not in webdav["config"]


def test_admin_storage_bucket_usage_reports_references_and_budget(client):
    login(client, "admin@example.com")
    settings = client.get("/admin/settings").json()["settings"]
    default_bucket = settings["storage_buckets"][0]
    secondary_root = client.app.state.settings.object_storage_path.parent / "usage-objects"
    created = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 3,
            "active_storage_bucket_id": default_bucket["id"],
            "storage_buckets": [
                default_bucket,
                {
                    "name": "Usage bucket",
                    "type": "local",
                    "space_budget_bytes": 123456,
                    "config": {"path": str(secondary_root)},
                },
            ],
        },
    )
    bucket = next(bucket for bucket in created.json()["settings"]["storage_buckets"] if bucket["name"] == "Usage bucket")

    profile = new_profile(client)
    with client.app.state.SessionLocal() as db:
        first = PersistentVersion(
            profile_id=profile["id"],
            bucket_id=bucket["id"],
            object_path="missing-first.bin",
            sha256="1" * 64,
            size=5,
        )
        second = PersistentVersion(
            profile_id=profile["id"],
            bucket_id=bucket["id"],
            object_path="missing-second.bin",
            sha256="2" * 64,
            size=7,
        )
        db.add_all([first, second])
        db.flush()
        db.add(PersistentCurrent(profile_id=profile["id"], version_id=second.id))
        db.add(PersistentDailyBackup(profile_id=profile["id"], backup_date=datetime(2026, 1, 1).date(), version_id=first.id))
        db.add(PersistentDailyBackup(profile_id=profile["id"], backup_date=datetime(2026, 1, 2).date(), version_id=second.id))
        db.commit()

    client.post("/logout")
    login(client, "admin@example.com")
    usage = client.get(f"/admin/storage-buckets/{bucket['id']}/usage")

    assert usage.status_code == 200
    assert usage.json() == {
        "bucket_id": bucket["id"],
        "file_count": 2,
        "total_size": 12,
        "backup_reference_count": 2,
        "current_reference_count": 1,
        "space_budget_bytes": 123456,
    }
    refreshed = client.get("/admin/settings").json()["settings"]
    refreshed_bucket = next(item for item in refreshed["storage_buckets"] if item["id"] == bucket["id"])
    assert refreshed_bucket["space_budget_bytes"] == 123456
    assert refreshed_bucket["usage_summary"] == {
        "file_count": 2,
        "total_size": 12,
        "backup_reference_count": 2,
        "current_reference_count": 1,
    }
    assert refreshed_bucket["is_config_locked"] is True


def test_referenced_storage_bucket_locks_connection_config_but_allows_name_and_budget(client):
    login(client, "admin@example.com")
    settings = client.get("/admin/settings").json()["settings"]
    default_bucket = settings["storage_buckets"][0]
    webdav_created = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 3,
            "storage_buckets": [
                default_bucket,
                {
                    "name": "Referenced WebDAV",
                    "type": "webdav",
                    "space_budget_bytes": 100,
                    "config": {
                        "base_url": "https://dav.example.test/root",
                        "username": "mas",
                        "password": "secret",
                        "root_path": "persistent",
                    },
                },
            ],
        },
    )
    bucket = next(bucket for bucket in webdav_created.json()["settings"]["storage_buckets"] if bucket["name"] == "Referenced WebDAV")
    profile = new_profile(client)
    with client.app.state.SessionLocal() as db:
        version = PersistentVersion(
            profile_id=profile["id"],
            bucket_id=bucket["id"],
            object_path="object.bin",
            sha256="a" * 64,
            size=3,
        )
        db.add(version)
        db.flush()
        db.add(PersistentCurrent(profile_id=profile["id"], version_id=version.id))
        db.commit()

    client.post("/logout")
    login(client, "admin@example.com")
    changed_connection = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 3,
            "storage_buckets": [
                default_bucket,
                {
                    "id": bucket["id"],
                    "name": "Referenced WebDAV",
                    "type": "webdav",
                    "space_budget_bytes": 100,
                    "config": {
                        "base_url": "https://changed.example.test/root",
                        "username": "mas",
                        "password": "",
                        "root_path": "persistent",
                    },
                },
            ],
        },
    )
    assert changed_connection.status_code == 409
    assert changed_connection.json()["detail"]["code"] == "storage_bucket_config_locked"

    renamed = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 3,
            "storage_buckets": [
                default_bucket,
                {
                    "id": bucket["id"],
                    "name": "Renamed WebDAV",
                    "type": "webdav",
                    "space_budget_bytes": 200,
                    "config": {
                        "base_url": "https://dav.example.test/root",
                        "username": "mas",
                        "password": "",
                        "root_path": "persistent",
                    },
                },
            ],
        },
    )

    assert renamed.status_code == 200
    renamed_bucket = next(item for item in renamed.json()["settings"]["storage_buckets"] if item["id"] == bucket["id"])
    assert renamed_bucket["name"] == "Renamed WebDAV"
    assert renamed_bucket["space_budget_bytes"] == 200


def test_admin_delete_storage_bucket_requires_confirmation_and_preserves_default(client):
    login(client, "admin@example.com")
    settings = client.get("/admin/settings").json()["settings"]
    default_bucket = settings["storage_buckets"][0]

    missing_confirmation = client.delete(f"/admin/storage-buckets/{default_bucket['id']}")

    assert missing_confirmation.status_code == 400
    assert missing_confirmation.json()["detail"]["code"] == "storage_bucket_delete_confirmation_required"
    confirmed_default = client.delete(f"/admin/storage-buckets/{default_bucket['id']}?confirm=true")
    assert confirmed_default.status_code == 409
    assert confirmed_default.json()["detail"]["code"] == "storage_bucket_in_use"


def test_confirmed_storage_bucket_delete_migrates_readable_current_and_removes_backups_only_from_database(client):
    login(client, "admin@example.com")
    settings = client.get("/admin/settings").json()["settings"]
    default_bucket = settings["storage_buckets"][0]
    secondary_root = client.app.state.settings.object_storage_path.parent / "delete-objects"
    created = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 3,
            "storage_buckets": [
                default_bucket,
                {
                    "name": "Delete me",
                    "type": "local",
                    "config": {"path": str(secondary_root)},
                },
            ],
        },
    )
    bucket = next(bucket for bucket in created.json()["settings"]["storage_buckets"] if bucket["name"] == "Delete me")
    assert client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 3,
            "active_storage_bucket_id": bucket["id"],
            "storage_buckets": created.json()["settings"]["storage_buckets"],
        },
    ).status_code == 200

    client.post("/logout")
    profile = new_profile(client)
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert upload_persistent(client, key, lease, b"first", now=base).status_code == 201
    assert upload_persistent(client, key, lease, b"second", now=base + timedelta(days=1)).status_code == 201
    with client.app.state.SessionLocal() as db:
        old_versions = list(db.scalars(select(PersistentVersion).where(PersistentVersion.profile_id == profile["id"])))
        old_paths = [version.object_path for version in old_versions]
    assert all((secondary_root / path).exists() for path in old_paths)

    client.post("/logout")
    login(client, "admin@example.com")
    deleted = client.delete(f"/admin/storage-buckets/{bucket['id']}?confirm=true")

    assert deleted.status_code == 200
    assert deleted.json() == {
        "deleted_backup_count": 2,
        "migrated_current_count": 1,
        "removed_current_count": 0,
        "deleted_version_count": 2,
    }
    settings_after = client.get("/admin/settings").json()["settings"]
    assert settings_after["active_storage_bucket_id"] == default_bucket["id"]
    assert all(item["id"] != bucket["id"] for item in settings_after["storage_buckets"])
    with client.app.state.SessionLocal() as db:
        current = db.scalar(select(PersistentCurrent).where(PersistentCurrent.profile_id == profile["id"]))
        migrated = db.get(PersistentVersion, current.version_id)
        assert migrated.bucket_id == default_bucket["id"]
        assert migrated.sha256 == old_versions[-1].sha256
        assert migrated.size == old_versions[-1].size
        assert db.scalars(select(PersistentDailyBackup).where(PersistentDailyBackup.profile_id == profile["id"])).all() == []
        assert db.scalars(select(PersistentVersion).where(PersistentVersion.bucket_id == bucket["id"])).all() == []
    assert client.get(f"/admin/profiles/{profile['id']}/persistent/current/download").content == b"second"
    assert all((secondary_root / path).exists() for path in old_paths)


def test_confirmed_storage_bucket_delete_removes_current_when_object_cannot_be_read(client):
    login(client, "admin@example.com")
    settings = client.get("/admin/settings").json()["settings"]
    default_bucket = settings["storage_buckets"][0]
    broken_root = client.app.state.settings.object_storage_path.parent / "broken-objects"
    created = client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 3,
            "storage_buckets": [
                default_bucket,
                {
                    "name": "Broken bucket",
                    "type": "local",
                    "config": {"path": str(broken_root)},
                },
            ],
        },
    )
    bucket = next(bucket for bucket in created.json()["settings"]["storage_buckets"] if bucket["name"] == "Broken bucket")
    profile = new_profile(client)
    with client.app.state.SessionLocal() as db:
        version = PersistentVersion(
            profile_id=profile["id"],
            bucket_id=bucket["id"],
            object_path="does-not-exist.bin",
            sha256="b" * 64,
            size=4,
        )
        db.add(version)
        db.flush()
        db.add(PersistentCurrent(profile_id=profile["id"], version_id=version.id))
        db.commit()

    client.post("/logout")
    login(client, "admin@example.com")
    deleted = client.delete(f"/admin/storage-buckets/{bucket['id']}?confirm=true")

    assert deleted.status_code == 200
    assert deleted.json()["migrated_current_count"] == 0
    assert deleted.json()["removed_current_count"] == 1
    with client.app.state.SessionLocal() as db:
        assert db.scalar(select(PersistentCurrent).where(PersistentCurrent.profile_id == profile["id"])) is None
        assert db.get(StorageBucket, bucket["id"]) is None


def test_public_config_web_url_uses_saved_frontend_url_or_origin_fallback(client):
    fallback = client.get("/v1/config/web-url")

    assert fallback.status_code == 200
    assert fallback.json() == {
        "backend_api_url": "http://testserver",
        "frontend_web_url": "http://testserver",
        "profile_keys_url": "http://testserver/account/profile-keys",
    }

    login(client, "admin@example.com")
    assert client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "https://portal.example.test/",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 3,
        },
    ).status_code == 200
    client.post("/logout")

    configured = client.get("/v1/config/web-url")
    assert configured.status_code == 200
    assert configured.json() == {
        "backend_api_url": "http://testserver",
        "frontend_web_url": "https://portal.example.test",
        "profile_keys_url": "https://portal.example.test/account/profile-keys",
    }


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


def test_profile_payload_storage_usage_totals_daily_backups_and_includes_limit(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    assert upload_persistent(client, key, lease, b"first", now=base).status_code == 201
    assert upload_persistent(client, key, lease, b"second", now=base + timedelta(days=1)).status_code == 201

    detail = client.get(f"/account/profiles/{profile['id']}")

    assert detail.status_code == 200
    assert detail.json()["profile"]["storage_usage"] == len(b"first") + len(b"second")
    assert detail.json()["profile"]["storage_limit"] == 10 * 1024 * 1024


def test_upload_storage_limit_uses_projected_daily_backup_usage(client):
    profile = new_profile(client)
    key = profile["profile_key"]
    lease = acquire_lock(client, key)
    base = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    client.post("/logout")
    login(client, "admin@example.com")
    assert client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 8,
            "max_active_profiles_per_account": 3,
        },
    ).status_code == 200
    client.post("/logout")
    login(client)

    first = upload_persistent(client, key, lease, b"12345", now=base)
    same_day_replacement = upload_persistent(client, key, lease, b"1234567", now=base + timedelta(hours=1))
    exceeded = upload_persistent(client, key, lease, b"99", now=base + timedelta(days=1))

    assert first.status_code == 201
    assert same_day_replacement.status_code == 201
    assert exceeded.status_code == 413
    assert exceeded.json()["detail"]["code"] == "profile_storage_limit_exceeded"
    assert client.get(f"/account/profiles/{profile['id']}").json()["profile"]["storage_usage"] == 7

    with client.app.state.SessionLocal() as db:
        versions = list(db.scalars(select(PersistentVersion).where(PersistentVersion.profile_id == profile["id"])))
        backups = list(db.scalars(select(PersistentDailyBackup).where(PersistentDailyBackup.profile_id == profile["id"])))
    assert len(versions) == 1
    assert len(backups) == 1


def test_profile_key_creation_respects_active_profile_limit(client):
    login(client, "admin@example.com")
    assert client.put(
        "/admin/settings",
        json={
            "backend_api_url": "",
            "frontend_web_url": "",
            "profile_storage_limit_bytes": 10 * 1024 * 1024,
            "max_active_profiles_per_account": 2,
        },
    ).status_code == 200
    client.post("/logout")
    login(client)

    assert client.post("/account/profile-keys", json={"display_name": "One"}).status_code == 201
    assert client.post("/account/profile-keys", json={"display_name": "Two"}).status_code == 201
    blocked = client.post("/account/profile-keys", json={"display_name": "Three"})

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "active_profile_limit_exceeded"
