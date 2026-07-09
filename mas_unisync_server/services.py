from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, Request
from sqlalchemy import delete, desc, func, or_, select
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
SETTING_BACKEND_API_URL = "backend_api_url"
SETTING_FRONTEND_WEB_URL = "frontend_web_url"
SETTING_PROFILE_STORAGE_LIMIT_BYTES = "profile_storage_limit_bytes"
SETTING_MAX_ACTIVE_PROFILES_PER_ACCOUNT = "max_active_profiles_per_account"
SUPPORTED_STORAGE_BUCKET_TYPES = {"local", "webdav"}
DEFAULT_LOCAL_BUCKET_NAME = "Docker local storage"


def sanitize_version(value: str | None) -> str | None:
    """Strip Python object reprs (e.g. '<function version at 0x...>') sent by buggy clients."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped.startswith('<') and stripped.endswith('>'):
        return None
    return stripped or None


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


def profile_payload(profile: Profile, storage_usage: int = 0, storage_limit: int = DEFAULT_PROFILE_STORAGE_LIMIT_BYTES) -> dict:
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
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
            created_at=request_now(request),
        )
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


def public_storage_bucket_config(bucket: StorageBucket) -> dict:
    config = storage_bucket_config(bucket)
    if bucket.type == "webdav":
        return {
            "base_url": normalize_url_setting(config.get("base_url")),
            "username": str(config.get("username") or ""),
            "root_path": str(config.get("root_path") or "").strip("/"),
            "has_password": bool(config.get("password")),
        }
    if bucket.type == "local":
        return {"path": str(config.get("path") or "")}
    return {}


def storage_bucket_payload(bucket: StorageBucket) -> dict:
    return {
        "id": bucket.id,
        "name": bucket.name,
        "type": bucket.type,
        "is_active": bucket.is_active,
        "config": public_storage_bucket_config(bucket),
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


def storage_for_bucket(bucket: StorageBucket) -> ObjectStorage:
    config = storage_bucket_config(bucket)
    if bucket.type == "local":
        return LocalObjectStorage(Path(str(config.get("path") or "./data/objects")))
    if bucket.type == "webdav":
        return WebDavObjectStorage(
            base_url=normalize_url_setting(config.get("base_url")),
            username=str(config.get("username") or ""),
            password=str(config.get("password") or ""),
            root_path=str(config.get("root_path") or "").strip("/"),
        )
    raise HTTPException(status_code=500, detail={"code": "unsupported_storage_bucket_type"})


def version_storage(db: Session, settings: Settings, version: PersistentVersion) -> ObjectStorage:
    return storage_for_bucket(storage_bucket_for_version(db, settings, version))


def get_version_bytes(db: Session, settings: Settings, version: PersistentVersion) -> bytes:
    return version_storage(db, settings, version).get(version.object_path)


def delete_version_object(db: Session, settings: Settings, bucket_id: int | None, object_path: str) -> None:
    if bucket_id is None:
        bucket = ensure_default_storage_bucket(db, settings)
    else:
        bucket = db.get(StorageBucket, bucket_id)
        if bucket is None:
            return
    storage_for_bucket(bucket).delete(object_path)


def normalize_storage_bucket_request(raw_bucket, existing: StorageBucket | None = None) -> tuple[str, str, dict]:
    name = (raw_bucket.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail={"code": "storage_bucket_name_required"})
    bucket_type = normalize_storage_bucket_type(raw_bucket.type)
    raw_config = raw_bucket.config or {}

    if bucket_type == "local":
        path = str(raw_config.get("path") or "").strip()
        if not path:
            raise HTTPException(status_code=422, detail={"code": "local_storage_path_required"})
        return name, bucket_type, {"path": path}

    base_url = normalize_url_setting(raw_config.get("base_url"))
    if not base_url:
        raise HTTPException(status_code=422, detail={"code": "webdav_base_url_required"})
    password = str(raw_config.get("password") or "")
    if password == "" and existing is not None and existing.type == "webdav":
        password = str(storage_bucket_config(existing).get("password") or "")
    return (
        name,
        bucket_type,
        {
            "base_url": base_url,
            "username": str(raw_config.get("username") or ""),
            "password": password,
            "root_path": str(raw_config.get("root_path") or "").strip("/"),
        },
    )


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
        "active_storage_bucket_id": active_bucket.id if active_bucket else None,
        "storage_buckets": [storage_bucket_payload(bucket) for bucket in buckets],
    }


def save_system_settings(db: Session, request: Request, payload) -> dict:
    now = request_now(request)
    write_system_setting(db, SETTING_BACKEND_API_URL, normalize_url_setting(payload.backend_api_url), now)
    write_system_setting(db, SETTING_FRONTEND_WEB_URL, normalize_url_setting(payload.frontend_web_url), now)
    write_system_setting(db, SETTING_PROFILE_STORAGE_LIMIT_BYTES, str(payload.profile_storage_limit_bytes), now)
    write_system_setting(db, SETTING_MAX_ACTIVE_PROFILES_PER_ACCOUNT, str(payload.max_active_profiles_per_account), now)
    ensure_default_storage_bucket(db, request.app.state.settings)
    requested_active_id = payload.active_storage_bucket_id
    if payload.storage_buckets is not None:
        for raw_bucket in payload.storage_buckets:
            existing = db.get(StorageBucket, raw_bucket.id) if raw_bucket.id is not None else None
            if raw_bucket.id is not None and existing is None:
                raise HTTPException(status_code=404, detail={"code": "storage_bucket_not_found"})
            name, bucket_type, config = normalize_storage_bucket_request(raw_bucket, existing)
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


def delete_storage_bucket(db: Session, settings: Settings, bucket_id: int) -> None:
    default_bucket = ensure_default_storage_bucket(db, settings)
    bucket = db.get(StorageBucket, bucket_id)
    if bucket is None:
        raise HTTPException(status_code=404, detail={"code": "storage_bucket_not_found"})
    referenced = db.scalar(
        select(func.count(PersistentVersion.id)).where(PersistentVersion.bucket_id == bucket.id)
    ) or 0
    if bucket.id == default_bucket.id or bucket.is_active or referenced > 0:
        raise HTTPException(status_code=409, detail={"code": "storage_bucket_in_use"})
    db.delete(bucket)


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
    storage = storage_for_bucket(bucket)
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

