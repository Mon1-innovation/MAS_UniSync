from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, timedelta, timezone

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
    User,
)
from .settings import Settings
from .storage import LocalObjectStorage


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


def profile_payload(profile: Profile, storage_usage: int = 0) -> dict:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "profile_key": profile.profile_key_plaintext,
        "storage_usage": storage_usage,
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


def require_lock(db: Session, profile_id: int, lease_token: str | None, now: datetime) -> Lock:
    if not lease_token:
        raise HTTPException(status_code=409, detail={"code": "invalid_lease"})
    lock = active_lock(db, profile_id, now)
    if lock is None or lock.lease_token != lease_token:
        raise HTTPException(status_code=409, detail={"code": "invalid_lease"})
    return lock


def store_upload(
    db: Session,
    storage: LocalObjectStorage,
    profile: Profile,
    data: bytes,
    renpy_version: str | None,
    mas_version: str | None,
    now: datetime,
) -> PersistentVersion:
    sha = hashlib.sha256(data).hexdigest()
    backup_date = now.date()
    backup = db.scalar(
        select(PersistentDailyBackup).where(
            PersistentDailyBackup.profile_id == profile.id,
            PersistentDailyBackup.backup_date == backup_date,
        )
    )

    old_object_path = None
    if backup is None:
        version = PersistentVersion(
            profile_id=profile.id,
            object_path="pending",
            sha256=sha,
            size=len(data),
            renpy_version=renpy_version,
            mas_version=mas_version,
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
        version.sha256 = sha
        version.size = len(data)
        version.renpy_version = renpy_version
        version.mas_version = mas_version
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
        storage.delete(old_object_path)
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
    storage: LocalObjectStorage,
    request: Request,
    actor: User,
    profile: Profile,
    action: str,
) -> None:
    object_paths = list(
        db.scalars(select(PersistentVersion.object_path).where(PersistentVersion.profile_id == profile.id))
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
    for object_path in object_paths:
        storage.delete(object_path)


def profile_storage_usage(db: Session, profile_id: int) -> int:
    current = current_version(db, profile_id)
    return current.size if current else 0


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
