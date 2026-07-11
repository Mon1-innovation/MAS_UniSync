from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import secrets
import base64
from datetime import date, datetime, timedelta, timezone
from ipaddress import ip_address, ip_network
from pathlib import Path

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request
from sqlalchemy import delete, desc, func, or_, select, update
from sqlalchemy.orm import Session

from .models import (
    AuditLog,
    Ban,
    Lock,
    PersistentCurrent,
    PersistentDailyBackup,
    PersistentVersion,
    Profile,
    StorageBucket,
    SystemSetting,
    User,
)
from .settings import Settings
from .storage import LocalObjectStorage, ObjectStorage, WebDavObjectStorage


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def request_now(request: Request) -> datetime:
    value = request.headers.get("X-Test-Now")
    if not value:
        return utc_now()
    return aware(datetime.fromisoformat(value))


def iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return aware(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def generate_profile_key() -> str:
    return "maspk_" + secrets.token_urlsafe(32)


DEFAULT_PROFILE_STORAGE_LIMIT_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_ACTIVE_PROFILES_PER_ACCOUNT = 3
DEFAULT_GUEST_KEY_RETENTION_DAYS = 360
SETTING_BACKEND_API_URL = "backend_api_url"
SETTING_FRONTEND_WEB_URL = "frontend_web_url"
SETTING_PROFILE_STORAGE_LIMIT_BYTES = "profile_storage_limit_bytes"
SETTING_MAX_ACTIVE_PROFILES_PER_ACCOUNT = "max_active_profiles_per_account"
SETTING_GUEST_KEY_RETENTION_DAYS = "guest_key_retention_days"
SUPPORTED_STORAGE_BUCKET_TYPES = {"local", "webdav"}
DEFAULT_LOCAL_BUCKET_NAME = "Docker local storage"
ENCRYPTED_STORAGE_PASSWORD_PREFIX = "fernet:"
GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/Mon1-innovation/MAS_UniSync/releases/latest"
CLIENT_RELEASE_ASSET_PREFIX = "MAS_UniSync-"
CLIENT_RELEASE_ASSET_SUFFIX = ".zip"
CLIENT_RELEASE_HTTP_TIMEOUT_SECONDS = 30.0
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CachedClientRelease:
    path: Path
    filename: str


def storage_secret_fernet(settings: Settings) -> Fernet:
    digest = hashlib.sha256(settings.session_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_storage_secret(settings: Settings, value: str) -> str:
    return ENCRYPTED_STORAGE_PASSWORD_PREFIX + storage_secret_fernet(settings).encrypt(value.encode()).decode()


def decrypt_storage_secret(settings: Settings, value: str) -> str:
    if not value:
        return ""
    if not value.startswith(ENCRYPTED_STORAGE_PASSWORD_PREFIX):
        return value
    token = value.removeprefix(ENCRYPTED_STORAGE_PASSWORD_PREFIX)
    try:
        return storage_secret_fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(status_code=500, detail={"code": "storage_secret_decrypt_failed"}) from exc


def sanitize_version(value: str | None) -> str | None:
    """Strip Python object reprs (e.g. '<function version at 0x...>') sent by buggy clients."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped.startswith('<') and stripped.endswith('>'):
        return None
    return stripped or None


def cache_latest_client_release(settings: Settings) -> CachedClientRelease:
    asset = latest_client_release_asset()
    cache_dir = settings.client_release_cache_path
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cache_dir / asset["name"]
    metadata_path = cache_dir / f"{asset['name']}.json"
    if client_release_cache_is_current(archive_path, metadata_path, asset):
        return CachedClientRelease(path=archive_path, filename=asset["name"])

    try:
        response = httpx.get(
            asset["download_url"],
            headers=github_headers(),
            follow_redirects=True,
            timeout=CLIENT_RELEASE_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail={"code": "client_release_download_failed"}) from exc

    content = response.content
    if asset["size"] is not None and len(content) != asset["size"]:
        raise HTTPException(status_code=502, detail={"code": "client_release_size_mismatch"})

    temp_path = archive_path.with_name(f"{archive_path.name}.tmp")
    temp_path.write_bytes(content)
    temp_path.replace(archive_path)
    metadata_path.write_text(json.dumps(client_release_metadata(asset), ensure_ascii=False, indent=2), encoding="utf-8")
    return CachedClientRelease(path=archive_path, filename=asset["name"])


def latest_client_release_asset() -> dict:
    try:
        response = httpx.get(
            GITHUB_LATEST_RELEASE_URL,
            headers=github_headers(),
            timeout=CLIENT_RELEASE_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail={"code": "client_release_lookup_failed"}) from exc

    payload = response.json()
    assets = payload.get("assets") if isinstance(payload, dict) else None
    if not isinstance(assets, list):
        raise HTTPException(status_code=502, detail={"code": "client_release_asset_not_found"})
    for asset in assets:
        normalized = normalize_client_release_asset(asset, payload.get("tag_name"))
        if normalized is not None:
            return normalized
    raise HTTPException(status_code=502, detail={"code": "client_release_asset_not_found"})


def normalize_client_release_asset(asset: object, tag_name: object) -> dict | None:
    if not isinstance(asset, dict):
        return None
    name = asset.get("name")
    download_url = asset.get("browser_download_url")
    if not isinstance(name, str) or not isinstance(download_url, str):
        return None
    if not name.startswith(CLIENT_RELEASE_ASSET_PREFIX) or not name.endswith(CLIENT_RELEASE_ASSET_SUFFIX):
        return None
    if Path(name).name != name:
        return None
    size = asset.get("size")
    asset_id = asset.get("id")
    return {
        "id": asset_id if isinstance(asset_id, int) else None,
        "name": name,
        "size": size if isinstance(size, int) and size >= 0 else None,
        "tag_name": tag_name if isinstance(tag_name, str) else "",
        "download_url": download_url,
    }


def client_release_cache_is_current(archive_path: Path, metadata_path: Path, asset: dict) -> bool:
    if not archive_path.is_file() or not metadata_path.is_file():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expected = client_release_metadata(asset)
    if metadata != expected:
        return False
    return asset["size"] is None or archive_path.stat().st_size == asset["size"]


def client_release_metadata(asset: dict) -> dict:
    return {
        "id": asset["id"],
        "name": asset["name"],
        "size": asset["size"],
        "tag_name": asset["tag_name"],
        "download_url": asset["download_url"],
    }


def github_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MAS-UniSync",
    }


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "flarum_user_id": user.flarum_user_id,
        "username": user.username,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "last_login_at": iso(user.last_login_at),
    }


def profile_payload(
    profile: Profile,
    storage_usage: int = 0,
    storage_limit: int = DEFAULT_PROFILE_STORAGE_LIMIT_BYTES,
    guest_retention_days: int = DEFAULT_GUEST_KEY_RETENTION_DAYS,
) -> dict:
    is_guest = profile.user.role == "guest"
    guest_expires_at = None
    if is_guest:
        guest_expires_at = aware(profile.last_used_at or profile.created_at) + timedelta(days=guest_retention_days)
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "profile_key": profile.profile_key_plaintext,
        "storage_usage": storage_usage,
        "storage_limit": storage_limit,
        "revoked_at": iso(profile.revoked_at),
        "last_used_at": iso(profile.last_used_at),
        "last_upload_at": iso(profile.last_upload_at),
        "created_at": iso(profile.created_at),
        "is_guest": is_guest,
        "guest_retention_days": guest_retention_days if is_guest else None,
        "guest_expires_at": iso(guest_expires_at),
    }


def version_payload(version: PersistentVersion) -> dict:
    return {
        "id": version.id,
        "profile_id": version.profile_id,
        "sha256": version.sha256,
        "size": version.size,
        "renpy_version": version.renpy_version,
        "mas_version": version.mas_version,
        "created_at": iso(version.created_at),
    }


def backup_payload(backup: PersistentDailyBackup, version: PersistentVersion) -> dict:
    payload = version_payload(version)
    payload.update({"id": backup.id, "backup_date": iso(backup.backup_date), "version_id": backup.version_id})
    return payload


def map_role(groups: list[dict], settings: Settings) -> str:
    for group in groups:
        group_id = str(group.get("id", ""))
        group_name = str(group.get("name", ""))
        if group_id in settings.admin_flarum_group_ids or group_name in settings.admin_flarum_group_names:
            return "admin"
    return "user"


def upsert_flarum_user(db: Session, profile: dict, settings: Settings, now: datetime) -> User:
    flarum_user_id = str(profile["flarum_user_id"])
    user = db.scalar(select(User).where(User.flarum_user_id == flarum_user_id))
    if user is None:
        user = User(flarum_user_id=flarum_user_id, username=profile["username"])
        db.add(user)
    user.username = profile["username"]
    user.display_name = profile.get("display_name")
    user.avatar_url = profile.get("avatar_url")
    user.flarum_groups_json = json.dumps(profile.get("groups", []), ensure_ascii=False)
    user.role = map_role(profile.get("groups", []), settings)
    user.last_login_at = now
    user.last_seen_at = now
    return user


def direct_client_host(request: Request) -> str | None:
    return request.client.host if request.client else None


def trusted_proxy_matches(client_host: str | None, trusted_proxy_ips: set[str]) -> bool:
    if not client_host or not trusted_proxy_ips:
        return False
    try:
        client_ip = ip_address(client_host)
    except ValueError:
        return False

    for trusted_proxy in trusted_proxy_ips:
        trusted_network = ip_network(trusted_proxy, strict=False)
        if client_ip.version == trusted_network.version and client_ip in trusted_network:
            return True
    return False


def first_x_forwarded_for_ip(request: Request) -> str | None:
    for value in request.headers.get("X-Forwarded-For", "").split(","):
        candidate = value.strip()
        if not candidate:
            continue
        try:
            ip_address(candidate)
        except ValueError:
            continue
        return candidate
    return None


def audit_ip_address(request: Request, settings: Settings) -> str | None:
    client_host = direct_client_host(request)
    if trusted_proxy_matches(client_host, settings.trusted_proxy_ips):
        return first_x_forwarded_for_ip(request) or client_host
    return client_host


def audit(
    db: Session,
    request: Request,
    actor: User | None,
    action: str,
    *,
    target_user_id: int | None = None,
    target_profile_id: int | None = None,
    target_profile_key_id: int | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            actor_role=actor.role if actor else None,
            action=action,
            target_user_id=target_user_id,
            target_profile_id=target_profile_id,
            target_profile_key_id=target_profile_key_id,
            ip_address=audit_ip_address(request, request.app.state.settings),
            user_agent=request.headers.get("User-Agent"),
            created_at=request_now(request),
        )
    )


def anonymize_audit_actor(db: Session, user_id: int) -> None:
    db.execute(
        update(AuditLog)
        .where(AuditLog.actor_user_id == user_id)
        .values(actor_user_id=None)
    )


def request_origin(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def normalize_url_setting(value: str | None) -> str:
    return (value or "").strip().rstrip("/")


def normalize_storage_bucket_type(value: str) -> str:
    bucket_type = value.strip().lower()
    if bucket_type not in SUPPORTED_STORAGE_BUCKET_TYPES:
        supported = ", ".join(sorted(SUPPORTED_STORAGE_BUCKET_TYPES))
        raise HTTPException(status_code=422, detail={"code": "unsupported_storage_bucket_type", "supported": supported})
    return bucket_type


def storage_bucket_config(bucket: StorageBucket) -> dict:
    try:
        value = json.loads(bucket.config_json or "{}")
    except json.JSONDecodeError:
        value = {}
    return value if isinstance(value, dict) else {}


def storage_bucket_space_budget_bytes(bucket_or_config: StorageBucket | dict) -> int | None:
    config = storage_bucket_config(bucket_or_config) if isinstance(bucket_or_config, StorageBucket) else bucket_or_config
    value = config.get("space_budget_bytes")
    if value is None or value == "":
        return None
    try:
        budget = int(value)
    except (TypeError, ValueError):
        return None
    return budget if budget >= 0 else None


def webdav_password_from_config(settings: Settings, config: dict) -> str:
    encrypted_password = str(config.get("password_encrypted") or "")
    if encrypted_password:
        return decrypt_storage_secret(settings, encrypted_password)
    return str(config.get("password") or "")


def public_storage_bucket_config(bucket: StorageBucket, settings: Settings) -> dict:
    config = storage_bucket_config(bucket)
    if bucket.type == "webdav":
        return {
            "base_url": normalize_url_setting(config.get("base_url")),
            "username": str(config.get("username") or ""),
            "root_path": str(config.get("root_path") or "").strip("/"),
            "has_password": bool(webdav_password_from_config(settings, config)),
        }
    if bucket.type == "local":
        return {"path": str(config.get("path") or "")}
    return {}


def storage_bucket_reference_summary(db: Session, bucket_id: int) -> dict:
    backup_count = db.scalar(
        select(func.count(PersistentDailyBackup.id))
        .join(PersistentVersion, PersistentVersion.id == PersistentDailyBackup.version_id)
        .where(PersistentVersion.bucket_id == bucket_id)
    ) or 0
    current_count = db.scalar(
        select(func.count(PersistentCurrent.profile_id))
        .join(PersistentVersion, PersistentVersion.id == PersistentCurrent.version_id)
        .where(PersistentVersion.bucket_id == bucket_id)
    ) or 0
    version_totals = db.execute(
        select(
            func.count(PersistentVersion.id),
            func.coalesce(func.sum(PersistentVersion.size), 0),
        ).where(PersistentVersion.bucket_id == bucket_id)
    ).one()
    return {
        "file_count": int(version_totals[0] or 0),
        "total_size": int(version_totals[1] or 0),
        "backup_reference_count": int(backup_count),
        "current_reference_count": int(current_count),
    }


def storage_bucket_has_references(db: Session, bucket_id: int) -> bool:
    return (db.scalar(select(func.count(PersistentVersion.id)).where(PersistentVersion.bucket_id == bucket_id)) or 0) > 0


def storage_bucket_usage_payload(db: Session, bucket: StorageBucket) -> dict:
    summary = storage_bucket_reference_summary(db, bucket.id)
    return {
        "bucket_id": bucket.id,
        **summary,
        "space_budget_bytes": storage_bucket_space_budget_bytes(bucket),
    }


def storage_bucket_payload(bucket: StorageBucket, settings: Settings, db: Session | None = None) -> dict:
    usage_summary = storage_bucket_reference_summary(db, bucket.id) if db is not None else None
    return {
        "id": bucket.id,
        "name": bucket.name,
        "type": bucket.type,
        "is_active": bucket.is_active,
        "space_budget_bytes": storage_bucket_space_budget_bytes(bucket),
        "usage_summary": usage_summary,
        "is_config_locked": bool(usage_summary and usage_summary["file_count"] > 0),
        "config": public_storage_bucket_config(bucket, settings),
    }


def ensure_default_storage_bucket(db: Session, settings: Settings) -> StorageBucket:
    bucket = db.scalar(select(StorageBucket).order_by(StorageBucket.id))
    if bucket is None:
        bucket = StorageBucket(
            name=DEFAULT_LOCAL_BUCKET_NAME,
            type="local",
            is_active=True,
            config_json=json.dumps({"path": str(settings.object_storage_path)}, ensure_ascii=False),
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        db.add(bucket)
        db.flush()
        return bucket

    if db.scalar(select(StorageBucket).where(StorageBucket.is_active.is_(True))) is None:
        bucket.is_active = True
        db.flush()
    return bucket


def storage_buckets(db: Session, settings: Settings) -> list[StorageBucket]:
    ensure_default_storage_bucket(db, settings)
    return list(db.scalars(select(StorageBucket).order_by(StorageBucket.id)))


def active_storage_bucket(db: Session, settings: Settings) -> StorageBucket:
    ensure_default_storage_bucket(db, settings)
    bucket = db.scalar(select(StorageBucket).where(StorageBucket.is_active.is_(True)).order_by(StorageBucket.id))
    if bucket is None:
        bucket = db.scalar(select(StorageBucket).order_by(StorageBucket.id))
        if bucket is None:
            raise HTTPException(status_code=500, detail={"code": "storage_bucket_missing"})
        bucket.is_active = True
        db.flush()
    return bucket


def storage_bucket_for_version(db: Session, settings: Settings, version: PersistentVersion) -> StorageBucket:
    if version.bucket_id is None:
        return ensure_default_storage_bucket(db, settings)
    bucket = db.get(StorageBucket, version.bucket_id)
    if bucket is None:
        raise HTTPException(status_code=500, detail={"code": "storage_bucket_missing", "bucket_id": version.bucket_id})
    return bucket


def storage_for_bucket(bucket: StorageBucket, settings: Settings | None = None) -> ObjectStorage:
    config = storage_bucket_config(bucket)
    if bucket.type == "local":
        return LocalObjectStorage(Path(str(config.get("path") or "./data/objects")))
    if bucket.type == "webdav":
        password = webdav_password_from_config(settings, config) if settings is not None else str(config.get("password") or "")
        return WebDavObjectStorage(
            base_url=normalize_url_setting(config.get("base_url")),
            username=str(config.get("username") or ""),
            password=password,
            root_path=str(config.get("root_path") or "").strip("/"),
        )
    raise HTTPException(status_code=500, detail={"code": "unsupported_storage_bucket_type"})


def test_storage_bucket(db: Session, settings: Settings, raw_bucket) -> None:
    existing = db.get(StorageBucket, raw_bucket.id) if raw_bucket.id is not None else None
    if raw_bucket.id is not None and existing is None:
        raise HTTPException(status_code=404, detail={"code": "storage_bucket_not_found"})
    name, bucket_type, config = normalize_storage_bucket_request(settings, raw_bucket, existing)
    bucket = StorageBucket(
        name=name,
        type=bucket_type,
        is_active=False,
        config_json=json.dumps(config, ensure_ascii=False),
    )
    storage = storage_for_bucket(bucket, settings)
    data = f"mas-unisync-storage-test:{secrets.token_hex(16)}".encode()
    sha = hashlib.sha256(data).hexdigest()
    object_path = ""
    try:
        try:
            object_path = storage.put(0, 0, sha, data)
        except Exception as exc:
            raise storage_bucket_test_exception("put", exc) from exc
        try:
            downloaded = storage.get(object_path)
        except Exception as exc:
            raise storage_bucket_test_exception("get", exc) from exc
        if downloaded != data:
            raise HTTPException(status_code=502, detail={"code": "storage_bucket_test_mismatch"})
    except HTTPException:
        raise
    finally:
        if object_path:
            try:
                storage.delete(object_path)
            except Exception as exc:
                raise storage_bucket_test_exception("delete", exc) from exc


def storage_bucket_test_exception(phase: str, exc: Exception) -> HTTPException:
    detail = {
        "code": "storage_bucket_test_failed",
        "phase": phase,
        "error_type": type(exc).__name__,
    }
    if isinstance(exc, httpx.HTTPStatusError):
        detail["upstream_status"] = exc.response.status_code
    return HTTPException(status_code=502, detail=detail)


def version_storage(db: Session, settings: Settings, version: PersistentVersion) -> ObjectStorage:
    return storage_for_bucket(storage_bucket_for_version(db, settings, version), settings)


def get_version_bytes(db: Session, settings: Settings, version: PersistentVersion) -> bytes:
    return version_storage(db, settings, version).get(version.object_path)


def delete_version_object(db: Session, settings: Settings, bucket_id: int | None, object_path: str) -> None:
    if bucket_id is None:
        bucket = ensure_default_storage_bucket(db, settings)
    else:
        bucket = db.get(StorageBucket, bucket_id)
        if bucket is None:
            return
    storage_for_bucket(bucket, settings).delete(object_path)


def normalize_storage_bucket_request(settings: Settings, raw_bucket, existing: StorageBucket | None = None) -> tuple[str, str, dict]:
    name = (raw_bucket.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail={"code": "storage_bucket_name_required"})
    bucket_type = normalize_storage_bucket_type(raw_bucket.type)
    raw_config = raw_bucket.config or {}
    raw_budget = getattr(raw_bucket, "space_budget_bytes", None)
    space_budget = None if raw_budget is None or raw_budget == "" else int(raw_budget)

    if bucket_type == "local":
        path = str(raw_config.get("path") or "").strip()
        if not path:
            raise HTTPException(status_code=422, detail={"code": "local_storage_path_required"})
        return name, bucket_type, {"path": path, "space_budget_bytes": space_budget}

    base_url = normalize_url_setting(raw_config.get("base_url"))
    if not base_url:
        raise HTTPException(status_code=422, detail={"code": "webdav_base_url_required"})
    password = str(raw_config.get("password") or "")
    if password == "" and existing is not None and existing.type == "webdav":
        password = webdav_password_from_config(settings, storage_bucket_config(existing))
    return (
        name,
        bucket_type,
        {
            "base_url": base_url,
            "username": str(raw_config.get("username") or ""),
            "password_encrypted": encrypt_storage_secret(settings, password) if password else "",
            "root_path": str(raw_config.get("root_path") or "").strip("/"),
            "space_budget_bytes": space_budget,
        },
    )


def storage_bucket_connection_signature(settings: Settings, bucket_type: str, config: dict) -> tuple:
    if bucket_type == "local":
        return ("local", str(config.get("path") or "").strip())
    if bucket_type == "webdav":
        return (
            "webdav",
            normalize_url_setting(config.get("base_url")),
            str(config.get("username") or ""),
            webdav_password_from_config(settings, config),
            str(config.get("root_path") or "").strip("/"),
        )
    return (bucket_type,)


def require_storage_bucket_config_unlocked(
    db: Session,
    settings: Settings,
    existing: StorageBucket,
    bucket_type: str,
    config: dict,
) -> None:
    if not storage_bucket_has_references(db, existing.id):
        return
    current_signature = storage_bucket_connection_signature(settings, existing.type, storage_bucket_config(existing))
    next_signature = storage_bucket_connection_signature(settings, bucket_type, config)
    if current_signature != next_signature:
        raise HTTPException(status_code=409, detail={"code": "storage_bucket_config_locked"})


def read_system_setting(db: Session, key: str) -> str | None:
    setting = db.get(SystemSetting, key)
    return setting.value if setting else None


def write_system_setting(db: Session, key: str, value: str, now: datetime) -> None:
    setting = db.get(SystemSetting, key)
    if setting is None:
        db.add(SystemSetting(key=key, value=value, updated_at=now))
    else:
        setting.value = value
        setting.updated_at = now


def profile_storage_limit_bytes(db: Session) -> int:
    raw = read_system_setting(db, SETTING_PROFILE_STORAGE_LIMIT_BYTES)
    if raw is None or raw == "":
        return DEFAULT_PROFILE_STORAGE_LIMIT_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_PROFILE_STORAGE_LIMIT_BYTES
    return value if value > 0 else DEFAULT_PROFILE_STORAGE_LIMIT_BYTES


def max_active_profiles_per_account(db: Session) -> int:
    raw = read_system_setting(db, SETTING_MAX_ACTIVE_PROFILES_PER_ACCOUNT)
    if raw is None or raw == "":
        return DEFAULT_MAX_ACTIVE_PROFILES_PER_ACCOUNT
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_ACTIVE_PROFILES_PER_ACCOUNT
    return value if value > 0 else DEFAULT_MAX_ACTIVE_PROFILES_PER_ACCOUNT


def guest_key_retention_days(db: Session) -> int:
    raw = read_system_setting(db, SETTING_GUEST_KEY_RETENTION_DAYS)
    if raw is None or raw == "":
        return DEFAULT_GUEST_KEY_RETENTION_DAYS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_GUEST_KEY_RETENTION_DAYS
    return value if value > 0 else DEFAULT_GUEST_KEY_RETENTION_DAYS


def system_settings_payload(db: Session, request: Request) -> dict:
    origin = request_origin(request)
    backend_api_url = normalize_url_setting(read_system_setting(db, SETTING_BACKEND_API_URL))
    frontend_web_url = normalize_url_setting(read_system_setting(db, SETTING_FRONTEND_WEB_URL))
    buckets = storage_buckets(db, request.app.state.settings)
    active_bucket = next((bucket for bucket in buckets if bucket.is_active), buckets[0] if buckets else None)
    return {
        "backend_api_url": backend_api_url or origin,
        "frontend_web_url": frontend_web_url or origin,
        "profile_storage_limit_bytes": profile_storage_limit_bytes(db),
        "max_active_profiles_per_account": max_active_profiles_per_account(db),
        "guest_key_retention_days": guest_key_retention_days(db),
        "active_storage_bucket_id": active_bucket.id if active_bucket else None,
        "storage_buckets": [storage_bucket_payload(bucket, request.app.state.settings, db) for bucket in buckets],
    }


def save_system_settings(db: Session, request: Request, payload) -> dict:
    now = request_now(request)
    write_system_setting(db, SETTING_BACKEND_API_URL, normalize_url_setting(payload.backend_api_url), now)
    write_system_setting(db, SETTING_FRONTEND_WEB_URL, normalize_url_setting(payload.frontend_web_url), now)
    write_system_setting(db, SETTING_PROFILE_STORAGE_LIMIT_BYTES, str(payload.profile_storage_limit_bytes), now)
    write_system_setting(db, SETTING_MAX_ACTIVE_PROFILES_PER_ACCOUNT, str(payload.max_active_profiles_per_account), now)
    if payload.guest_key_retention_days is not None:
        write_system_setting(db, SETTING_GUEST_KEY_RETENTION_DAYS, str(payload.guest_key_retention_days), now)
    ensure_default_storage_bucket(db, request.app.state.settings)
    requested_active_id = payload.active_storage_bucket_id
    if payload.storage_buckets is not None:
        for raw_bucket in payload.storage_buckets:
            existing = db.get(StorageBucket, raw_bucket.id) if raw_bucket.id is not None else None
            if raw_bucket.id is not None and existing is None:
                raise HTTPException(status_code=404, detail={"code": "storage_bucket_not_found"})
            name, bucket_type, config = normalize_storage_bucket_request(request.app.state.settings, raw_bucket, existing)
            if existing is None:
                existing = StorageBucket(
                    name=name,
                    type=bucket_type,
                    is_active=False,
                    config_json=json.dumps(config, ensure_ascii=False),
                    created_at=now,
                    updated_at=now,
                )
                db.add(existing)
                db.flush()
            else:
                require_storage_bucket_config_unlocked(
                    db,
                    request.app.state.settings,
                    existing,
                    bucket_type,
                    config,
                )
                existing.name = name
                existing.type = bucket_type
                existing.config_json = json.dumps(config, ensure_ascii=False)
                existing.updated_at = now
            if payload.active_storage_bucket_id is None and raw_bucket.is_active:
                requested_active_id = existing.id

    if requested_active_id is not None:
        active = db.get(StorageBucket, requested_active_id)
        if active is None:
            raise HTTPException(status_code=404, detail={"code": "storage_bucket_not_found"})
        for bucket in db.scalars(select(StorageBucket)):
            bucket.is_active = bucket.id == active.id
            bucket.updated_at = now
    db.flush()
    return system_settings_payload(db, request)


def delete_storage_bucket(db: Session, settings: Settings, bucket_id: int) -> dict:
    default_bucket = ensure_default_storage_bucket(db, settings)
    bucket = db.get(StorageBucket, bucket_id)
    if bucket is None:
        raise HTTPException(status_code=404, detail={"code": "storage_bucket_not_found"})
    if bucket.id == default_bucket.id:
        raise HTTPException(status_code=409, detail={"code": "storage_bucket_in_use"})

    old_storage = storage_for_bucket(bucket, settings)
    local_storage = storage_for_bucket(default_bucket, settings)
    summary = {
        "deleted_backup_count": 0,
        "migrated_current_count": 0,
        "removed_current_count": 0,
        "deleted_version_count": 0,
    }

    if bucket.is_active:
        default_bucket.is_active = True
        default_bucket.updated_at = utc_now()
        bucket.is_active = False

    backup_rows = list(
        db.scalars(
            select(PersistentDailyBackup)
            .join(PersistentVersion, PersistentVersion.id == PersistentDailyBackup.version_id)
            .where(PersistentVersion.bucket_id == bucket.id)
        )
    )
    for backup in backup_rows:
        db.delete(backup)
    summary["deleted_backup_count"] = len(backup_rows)

    current_rows = list(
        db.execute(
            select(PersistentCurrent, PersistentVersion)
            .join(PersistentVersion, PersistentVersion.id == PersistentCurrent.version_id)
            .where(PersistentVersion.bucket_id == bucket.id)
        )
    )
    for current, version in current_rows:
        try:
            data = old_storage.get(version.object_path)
        except Exception:
            db.delete(current)
            summary["removed_current_count"] += 1
            continue
        migrated = PersistentVersion(
            profile_id=version.profile_id,
            bucket_id=default_bucket.id,
            object_path="pending",
            sha256=version.sha256,
            size=version.size,
            renpy_version=version.renpy_version,
            mas_version=version.mas_version,
            created_at=version.created_at,
        )
        db.add(migrated)
        db.flush()
        migrated.object_path = local_storage.put(migrated.profile_id, migrated.id, migrated.sha256, data)
        current.version_id = migrated.id
        current.updated_at = utc_now()
        summary["migrated_current_count"] += 1

    db.flush()
    referenced_by_backup = select(PersistentDailyBackup.version_id)
    referenced_by_current = select(PersistentCurrent.version_id)
    old_versions = list(
        db.scalars(
            select(PersistentVersion).where(
                PersistentVersion.bucket_id == bucket.id,
                PersistentVersion.id.not_in(referenced_by_backup),
                PersistentVersion.id.not_in(referenced_by_current),
            )
        )
    )
    for version in old_versions:
        db.delete(version)
    summary["deleted_version_count"] = len(old_versions)
    db.delete(bucket)
    return summary


def active_ban(db: Session, target_type: str, target_id: int, now: datetime) -> Ban | None:
    return db.scalar(
        select(Ban)
        .where(
            Ban.target_type == target_type,
            Ban.target_id == target_id,
            Ban.revoked_at.is_(None),
            or_(Ban.expires_at.is_(None), Ban.expires_at > now),
        )
        .order_by(desc(Ban.created_at))
    )


def ban_for_profile(db: Session, profile: Profile, now: datetime) -> Ban | None:
    return (
        active_ban(db, "key", profile.id, now)
        or active_ban(db, "profile", profile.id, now)
        or active_ban(db, "user", profile.user_id, now)
    )


def banned_exception(ban: Ban) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={"code": "banned", "target_type": ban.target_type, "reason": ban.reason},
    )


def get_profile_by_key(db: Session, key: str | None, now: datetime, *, check_ban: bool = True) -> Profile:
    if not key:
        raise HTTPException(status_code=401, detail={"code": "missing_profile_key"})
    profile = db.scalar(
        select(Profile).where(Profile.profile_key_plaintext == key, Profile.revoked_at.is_(None))
    )
    if profile is None:
        raise HTTPException(status_code=401, detail={"code": "invalid_profile_key"})
    if check_ban:
        ban = ban_for_profile(db, profile, now)
        if ban:
            raise banned_exception(ban)
    profile.last_used_at = now
    return profile


def current_version(db: Session, profile_id: int) -> PersistentVersion | None:
    row = db.scalar(select(PersistentCurrent).where(PersistentCurrent.profile_id == profile_id))
    if row is None:
        return None
    return db.get(PersistentVersion, row.version_id)


def require_current_version(db: Session, profile_id: int) -> PersistentVersion:
    version = current_version(db, profile_id)
    if version is None:
        raise HTTPException(status_code=404, detail={"code": "no_current_persistent"})
    return version


def active_lock(db: Session, profile_id: int, now: datetime) -> Lock | None:
    lock = db.scalar(select(Lock).where(Lock.profile_id == profile_id))
    if lock is None:
        return None
    if aware(lock.expires_at) <= now:
        return None
    return lock



def cleanup_expired_locks(db: Session, now: datetime) -> int:
    """Delete all lock rows whose expires_at is in the past. Returns count of removed rows."""
    result = db.execute(delete(Lock).where(Lock.expires_at <= now))
    db.commit()
    return result.rowcount


def cleanup_expired_guest_profiles(db: Session, settings: Settings, now: datetime) -> dict[str, int]:
    cutoff = now - timedelta(days=guest_key_retention_days(db))
    profiles = list(
        db.scalars(
            select(Profile)
            .join(User, User.id == Profile.user_id)
            .where(
                User.role == "guest",
                func.coalesce(Profile.last_used_at, Profile.created_at) < cutoff,
            )
            .order_by(Profile.id)
        )
    )
    result = {"deleted": 0, "storage_failures": 0}
    for profile in profiles:
        owner = profile.user
        versions = list(
            db.scalars(select(PersistentVersion).where(PersistentVersion.profile_id == profile.id))
        )
        try:
            for version in versions:
                delete_version_object(db, settings, version.bucket_id, version.object_path)
        except Exception:
            logger.exception("Failed to delete stored objects for expired guest profile %s", profile.id)
            db.add(
                AuditLog(
                    actor_user_id=None,
                    actor_role="system",
                    action="system.guest_profile.cleanup_storage_failed",
                    target_user_id=owner.id,
                    target_profile_id=profile.id,
                    target_profile_key_id=profile.id,
                    created_at=now,
                )
            )
            db.commit()
            result["storage_failures"] += 1
            continue

        owner_id = owner.id
        profile_id = profile.id
        db.add(
            AuditLog(
                actor_user_id=None,
                actor_role="system",
                action="system.guest_profile.cleanup",
                target_user_id=owner_id,
                target_profile_id=profile_id,
                target_profile_key_id=profile_id,
                created_at=now,
            )
        )
        db.execute(delete(Lock).where(Lock.profile_id == profile_id))
        db.execute(delete(PersistentCurrent).where(PersistentCurrent.profile_id == profile_id))
        db.execute(delete(PersistentDailyBackup).where(PersistentDailyBackup.profile_id == profile_id))
        db.execute(delete(PersistentVersion).where(PersistentVersion.profile_id == profile_id))
        db.execute(
            delete(Ban).where(
                Ban.target_type.in_(("profile", "key")),
                Ban.target_id == profile_id,
            )
        )
        db.delete(profile)
        db.flush()
        remaining_profiles = db.scalar(
            select(func.count(Profile.id)).where(Profile.user_id == owner_id)
        ) or 0
        if remaining_profiles == 0:
            db.execute(delete(Ban).where(Ban.target_type == "user", Ban.target_id == owner_id))
            anonymize_audit_actor(db, owner_id)
            db.delete(owner)
        db.commit()
        result["deleted"] += 1
    return result

def require_lock(db: Session, profile_id: int, lease_token: str | None, now: datetime) -> Lock:
    if not lease_token:
        raise HTTPException(status_code=409, detail={"code": "invalid_lease"})
    lock = active_lock(db, profile_id, now)
    if lock is None or lock.lease_token != lease_token:
        raise HTTPException(status_code=409, detail={"code": "invalid_lease"})
    return lock


def active_profile_count_for_user(db: Session, user_id: int) -> int:
    return db.scalar(
        select(func.count(Profile.id)).where(Profile.user_id == user_id, Profile.revoked_at.is_(None))
    ) or 0


def projected_profile_storage_usage(db: Session, profile_id: int, backup_date: date, incoming_size: int) -> int:
    current_usage = profile_storage_usage(db, profile_id)
    backup = db.scalar(
        select(PersistentDailyBackup).where(
            PersistentDailyBackup.profile_id == profile_id,
            PersistentDailyBackup.backup_date == backup_date,
        )
    )
    replaced_size = 0
    if backup is not None:
        version = db.get(PersistentVersion, backup.version_id)
        replaced_size = version.size if version else 0
    return current_usage - replaced_size + incoming_size


def store_upload(
    db: Session,
    settings: Settings,
    profile: Profile,
    data: bytes,
    renpy_version: str | None,
    mas_version: str | None,
    now: datetime,
) -> PersistentVersion:
    sha = hashlib.sha256(data).hexdigest()
    backup_date = now.date()
    bucket = active_storage_bucket(db, settings)
    storage = storage_for_bucket(bucket, settings)
    backup = db.scalar(
        select(PersistentDailyBackup).where(
            PersistentDailyBackup.profile_id == profile.id,
            PersistentDailyBackup.backup_date == backup_date,
        )
    )

    old_object_path = None
    old_bucket_id = None
    if backup is None:
        version = PersistentVersion(
            profile_id=profile.id,
            bucket_id=bucket.id,
            object_path="pending",
            sha256=sha,
            size=len(data),
            renpy_version=sanitize_version(renpy_version),
            mas_version=sanitize_version(mas_version),
            created_at=now,
        )
        db.add(version)
        db.flush()
        db.add(
            PersistentDailyBackup(
                profile_id=profile.id,
                backup_date=backup_date,
                version_id=version.id,
                created_at=now,
            )
        )
    else:
        version = db.get(PersistentVersion, backup.version_id)
        if version is None:
            raise HTTPException(status_code=500, detail={"code": "persistent_version_missing"})
        old_object_path = version.object_path
        old_bucket_id = version.bucket_id
        version.bucket_id = bucket.id
        version.sha256 = sha
        version.size = len(data)
        version.renpy_version = sanitize_version(renpy_version)
        version.mas_version = sanitize_version(mas_version)
        version.created_at = now
        backup.created_at = now

    version.object_path = storage.put(profile.id, version.id, sha, data)

    current = db.get(PersistentCurrent, profile.id)
    if current is None:
        db.add(PersistentCurrent(profile_id=profile.id, version_id=version.id, updated_at=now))
    else:
        current.version_id = version.id
        current.updated_at = now

    profile.last_upload_at = now
    db.flush()
    if old_object_path is not None and old_object_path != version.object_path:
        delete_version_object(db, settings, old_bucket_id, old_object_path)
    prune_backups(db, profile.id)
    return version


def prune_backups(db: Session, profile_id: int) -> None:
    backups = list(
        db.scalars(
            select(PersistentDailyBackup)
            .where(PersistentDailyBackup.profile_id == profile_id)
            .order_by(desc(PersistentDailyBackup.backup_date), desc(PersistentDailyBackup.id))
        )
    )
    for old in backups[10:]:
        db.delete(old)


def restore_backup(db: Session, profile_id: int, backup_id: int, now: datetime) -> PersistentVersion:
    backup = db.scalar(
        select(PersistentDailyBackup).where(
            PersistentDailyBackup.id == backup_id,
            PersistentDailyBackup.profile_id == profile_id,
        )
    )
    if backup is None:
        raise HTTPException(status_code=404, detail={"code": "backup_not_found"})
    current = db.get(PersistentCurrent, profile_id)
    if current is None:
        db.add(PersistentCurrent(profile_id=profile_id, version_id=backup.version_id, updated_at=now))
    else:
        current.version_id = backup.version_id
        current.updated_at = now
    return db.get(PersistentVersion, backup.version_id)


def delete_profile_key(
    db: Session,
    settings: Settings,
    request: Request,
    actor: User,
    profile: Profile,
    action: str,
) -> None:
    object_refs = list(
        db.execute(
            select(PersistentVersion.bucket_id, PersistentVersion.object_path).where(
                PersistentVersion.profile_id == profile.id
            )
        )
    )
    audit(
        db,
        request,
        actor,
        action,
        target_user_id=profile.user_id,
        target_profile_id=profile.id,
        target_profile_key_id=profile.id,
    )
    db.execute(delete(Lock).where(Lock.profile_id == profile.id))
    db.execute(delete(PersistentCurrent).where(PersistentCurrent.profile_id == profile.id))
    db.execute(delete(PersistentDailyBackup).where(PersistentDailyBackup.profile_id == profile.id))
    db.execute(delete(PersistentVersion).where(PersistentVersion.profile_id == profile.id))
    db.execute(
        delete(Ban).where(
            Ban.target_type == "key",
            Ban.target_id == profile.id,
            Ban.revoked_at.is_(None),
        )
    )
    db.delete(profile)
    db.commit()
    for bucket_id, object_path in object_refs:
        delete_version_object(db, settings, bucket_id, object_path)


def profile_storage_usage(db: Session, profile_id: int) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(PersistentVersion.size), 0))
        .select_from(PersistentDailyBackup)
        .join(PersistentVersion, PersistentVersion.id == PersistentDailyBackup.version_id)
        .where(PersistentDailyBackup.profile_id == profile_id)
    ) or 0


def user_storage_usage(db: Session, user_id: int) -> int:
    total = 0
    for profile in db.scalars(select(Profile).where(Profile.user_id == user_id)):
        total += profile_storage_usage(db, profile.id)
    return total


def active_ban_status(db: Session, user: User, now: datetime) -> bool:
    if active_ban(db, "user", user.id, now):
        return True
    for profile in user.profiles:
        if ban_for_profile(db, profile, now):
            return True
    return False

