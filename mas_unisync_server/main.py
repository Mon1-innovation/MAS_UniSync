from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .auth import admin_user, current_user, get_db
from .database import Base, make_engine, make_sessionmaker
from .flarum import FlarumClient
from .models import AuditLog, Ban, Lock, PersistentDailyBackup, PersistentVersion, Profile, User
from .services import (
    active_ban,
    active_ban_status,
    active_lock,
    audit,
    aware,
    backup_payload,
    banned_exception,
    generate_profile_key,
    get_profile_by_key,
    profile_payload,
    request_now,
    require_current_version,
    require_lock,
    restore_backup,
    store_upload,
    upsert_flarum_user,
    user_payload,
    user_storage_usage,
    version_payload,
)
from .schemas import BanRequest, LoginRequest, ProfileCreateRequest
from .settings import Settings
from .storage import LocalObjectStorage


def create_app(settings: Settings | None = None, flarum_client=None) -> FastAPI:
    settings = settings or Settings()
    flarum_client = flarum_client or FlarumClient(settings.flarum_url)
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    SessionLocal = make_sessionmaker(engine)
    storage = LocalObjectStorage(settings.object_storage_path)

    app = FastAPI(title="MAS UniSync Server")
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax")
    app.state.settings = settings
    app.state.SessionLocal = SessionLocal
    app.state.storage = storage
    app.state.flarum_client = flarum_client

    @app.post("/login/flarum")
    async def login_flarum(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
        now = request_now(request)
        try:
            token = await request.app.state.flarum_client.login(payload.identification, payload.password)
            profile = await request.app.state.flarum_client.get_user(token["token"], str(token["user_id"]))
        except Exception as exc:
            raise HTTPException(status_code=401, detail={"code": "invalid_flarum_credentials"}) from exc
        user = upsert_flarum_user(db, profile, request.app.state.settings, now)
        db.commit()
        request.session["user_id"] = user.id
        return {"user": user_payload(user)}

    @app.post("/logout", status_code=204)
    def logout(request: Request):
        request.session.clear()
        return Response(status_code=204)

    def owned_profile_or_404(db: Session, profile_id: int, user: User) -> Profile:
        profile = db.get(Profile, profile_id)
        if profile is None or profile.user_id != user.id:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        return profile

    @app.get("/account/profile-keys")
    def list_profile_keys(user: User = Depends(current_user), db: Session = Depends(get_db)):
        profiles = list(
            db.scalars(select(Profile).where(Profile.user_id == user.id).order_by(Profile.id))
        )
        return {"items": [profile_payload(profile) for profile in profiles]}

    @app.post("/account/profile-keys", status_code=201)
    def create_profile_key(
        payload: ProfileCreateRequest,
        request: Request,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        profile = Profile(
            user_id=user.id,
            profile_key_plaintext=generate_profile_key(),
            display_name=payload.display_name,
            created_at=request_now(request),
            updated_at=request_now(request),
        )
        db.add(profile)
        db.flush()
        audit(
            db,
            request,
            user,
            "profile_key.create",
            target_user_id=user.id,
            target_profile_id=profile.id,
            target_profile_key_id=profile.id,
        )
        db.commit()
        return profile_payload(profile)

    @app.post("/account/profile-keys/{profile_id}/refresh")
    def refresh_profile_key(
        profile_id: int,
        request: Request,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        profile = db.get(Profile, profile_id)
        if profile is None or profile.user_id != user.id:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        profile.profile_key_plaintext = generate_profile_key()
        profile.updated_at = request_now(request)
        audit(
            db,
            request,
            user,
            "profile_key.refresh",
            target_user_id=user.id,
            target_profile_id=profile.id,
            target_profile_key_id=profile.id,
        )
        db.commit()
        return profile_payload(profile)

    @app.post("/account/profile-keys/{profile_id}/revoke")
    def revoke_profile_key(
        profile_id: int,
        request: Request,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        profile = db.get(Profile, profile_id)
        if profile is None or profile.user_id != user.id:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        profile.revoked_at = request_now(request)
        audit(
            db,
            request,
            user,
            "profile_key.revoke",
            target_user_id=user.id,
            target_profile_id=profile.id,
            target_profile_key_id=profile.id,
        )
        db.commit()
        return profile_payload(profile)

    @app.get("/account/profiles/{profile_id}")
    def get_account_profile(profile_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
        profile = owned_profile_or_404(db, profile_id, user)
        return {"profile": profile_payload(profile)}

    @app.get("/account/profiles/{profile_id}/persistent/current")
    def account_persistent_current(profile_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
        profile = owned_profile_or_404(db, profile_id, user)
        return version_payload(require_current_version(db, profile.id))

    @app.get("/account/profiles/{profile_id}/persistent/current/download")
    def account_download_current(
        profile_id: int,
        request: Request,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        profile = owned_profile_or_404(db, profile_id, user)
        version = require_current_version(db, profile.id)
        return StreamingResponse(
            iter([request.app.state.storage.get(version.object_path)]),
            media_type="application/octet-stream",
        )

    @app.get("/account/profiles/{profile_id}/persistent/backups")
    def account_list_backups(profile_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
        profile = owned_profile_or_404(db, profile_id, user)
        rows = db.execute(
            select(PersistentDailyBackup, PersistentVersion)
            .join(PersistentVersion, PersistentVersion.id == PersistentDailyBackup.version_id)
            .where(PersistentDailyBackup.profile_id == profile.id)
            .order_by(desc(PersistentDailyBackup.backup_date))
        ).all()
        return {"items": [backup_payload(backup, version) for backup, version in rows]}

    @app.get("/account/profiles/{profile_id}/persistent/backups/{backup_id}/download")
    def account_download_backup(
        profile_id: int,
        backup_id: int,
        request: Request,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        profile = owned_profile_or_404(db, profile_id, user)
        backup = db.scalar(select(PersistentDailyBackup).where(PersistentDailyBackup.id == backup_id, PersistentDailyBackup.profile_id == profile.id))
        if backup is None:
            raise HTTPException(status_code=404, detail={"code": "backup_not_found"})
        version = db.get(PersistentVersion, backup.version_id)
        return StreamingResponse(
            iter([request.app.state.storage.get(version.object_path)]),
            media_type="application/octet-stream",
        )

    def profile_from_header(request: Request, db: Session, profile_key: str | None) -> Profile:
        profile = get_profile_by_key(db, profile_key, request_now(request), check_ban=True)
        db.commit()
        return profile

    @app.get("/v1/profile/resolve")
    def resolve_profile(
        request: Request,
        db: Session = Depends(get_db),
        profile_key: str | None = Header(default=None, alias="X-MAS-Profile-Key"),
    ):
        profile = profile_from_header(request, db, profile_key)
        return {"profile": profile_payload(profile)}

    @app.post("/v1/locks/acquire")
    def acquire_lock(
        request: Request,
        db: Session = Depends(get_db),
        profile_key: str | None = Header(default=None, alias="X-MAS-Profile-Key"),
    ):
        now = request_now(request)
        profile = get_profile_by_key(db, profile_key, now)
        settings = request.app.state.settings
        existing = db.scalar(select(Lock).where(Lock.profile_id == profile.id))
        if existing and aware(existing.expires_at) > now:
            raise HTTPException(status_code=409, detail={"code": "lock_held"})
        lease_token = generate_profile_key().replace("maspk_", "lease_", 1)
        expires_at = now + timedelta(seconds=settings.lock_ttl_seconds)
        if existing is None:
            existing = Lock(profile_id=profile.id, lease_token=lease_token, acquired_at=now, heartbeat_at=now, expires_at=expires_at)
            db.add(existing)
        else:
            existing.lease_token = lease_token
            existing.acquired_at = now
            existing.heartbeat_at = now
            existing.expires_at = expires_at
        db.commit()
        return {
            "lock_id": existing.id,
            "profile_id": profile.id,
            "lease_token": existing.lease_token,
            "expires_at": aware(existing.expires_at).isoformat(),
        }

    @app.post("/v1/locks/heartbeat")
    def heartbeat_lock(
        request: Request,
        db: Session = Depends(get_db),
        profile_key: str | None = Header(default=None, alias="X-MAS-Profile-Key"),
        lease_token: str | None = Header(default=None, alias="X-MAS-Lease-Token"),
    ):
        now = request_now(request)
        profile = get_profile_by_key(db, profile_key, now)
        lock = require_lock(db, profile.id, lease_token, now)
        lock.heartbeat_at = now
        lock.expires_at = now + timedelta(seconds=request.app.state.settings.lock_ttl_seconds)
        db.commit()
        return {"lease_token": lock.lease_token, "expires_at": aware(lock.expires_at).isoformat()}

    @app.post("/v1/locks/release", status_code=204)
    def release_lock(
        request: Request,
        db: Session = Depends(get_db),
        profile_key: str | None = Header(default=None, alias="X-MAS-Profile-Key"),
        lease_token: str | None = Header(default=None, alias="X-MAS-Lease-Token"),
    ):
        now = request_now(request)
        profile = get_profile_by_key(db, profile_key, now)
        lock = require_lock(db, profile.id, lease_token, now)
        db.delete(lock)
        db.commit()
        return Response(status_code=204)

    @app.get("/v1/persistent/current")
    def persistent_current(
        request: Request,
        db: Session = Depends(get_db),
        profile_key: str | None = Header(default=None, alias="X-MAS-Profile-Key"),
    ):
        profile = profile_from_header(request, db, profile_key)
        return version_payload(require_current_version(db, profile.id))

    @app.post("/v1/persistent/upload", status_code=201)
    async def upload_persistent(
        request: Request,
        file: UploadFile = File(...),
        renpy_version: str | None = Form(default=None),
        mas_version: str | None = Form(default=None),
        db: Session = Depends(get_db),
        profile_key: str | None = Header(default=None, alias="X-MAS-Profile-Key"),
        lease_token: str | None = Header(default=None, alias="X-MAS-Lease-Token"),
    ):
        now = request_now(request)
        profile = get_profile_by_key(db, profile_key, now)
        require_lock(db, profile.id, lease_token, now)
        data = await file.read()
        version = store_upload(db, request.app.state.storage, profile, data, renpy_version, mas_version, now)
        db.commit()
        return version_payload(version)

    @app.get("/v1/persistent/download")
    def download_persistent(
        request: Request,
        db: Session = Depends(get_db),
        profile_key: str | None = Header(default=None, alias="X-MAS-Profile-Key"),
    ):
        profile = profile_from_header(request, db, profile_key)
        version = require_current_version(db, profile.id)
        return StreamingResponse(
            iter([request.app.state.storage.get(version.object_path)]),
            media_type="application/octet-stream",
        )

    @app.get("/v1/persistent/backups")
    def list_backups(
        request: Request,
        db: Session = Depends(get_db),
        profile_key: str | None = Header(default=None, alias="X-MAS-Profile-Key"),
    ):
        profile = profile_from_header(request, db, profile_key)
        rows = db.execute(
            select(PersistentDailyBackup, PersistentVersion)
            .join(PersistentVersion, PersistentVersion.id == PersistentDailyBackup.version_id)
            .where(PersistentDailyBackup.profile_id == profile.id)
            .order_by(desc(PersistentDailyBackup.backup_date))
        ).all()
        return {"items": [backup_payload(backup, version) for backup, version in rows]}

    @app.post("/v1/persistent/backups/{backup_id}/restore")
    def restore_user_backup(
        backup_id: int,
        request: Request,
        db: Session = Depends(get_db),
        profile_key: str | None = Header(default=None, alias="X-MAS-Profile-Key"),
    ):
        now = request_now(request)
        profile = get_profile_by_key(db, profile_key, now)
        version = restore_backup(db, profile.id, backup_id, now)
        db.commit()
        return version_payload(version)

    def user_list_item(db: Session, user: User, now):
        profile_count = db.scalar(select(func.count(Profile.id)).where(Profile.user_id == user.id)) or 0
        last_upload = db.scalar(select(func.max(Profile.last_upload_at)).where(Profile.user_id == user.id))
        lock_status = "none"
        for profile in db.scalars(select(Profile).where(Profile.user_id == user.id)):
            if active_lock(db, profile.id, now):
                lock_status = "active"
                break
        payload = user_payload(user)
        payload.update(
            {
                "profile_count": profile_count,
                "storage_usage": user_storage_usage(db, user.id),
                "last_upload_at": last_upload.isoformat() if last_upload else None,
                "last_submod_use": max([p.last_used_at for p in user.profiles if p.last_used_at] or [None]),
                "lock_status": lock_status,
                "ban_status": active_ban_status(db, user, now),
            }
        )
        if payload["last_submod_use"] is not None:
            payload["last_submod_use"] = payload["last_submod_use"].isoformat()
        return payload

    @app.get("/admin/users")
    def admin_users(request: Request, _: User = Depends(admin_user), db: Session = Depends(get_db)):
        now = request_now(request)
        users = list(db.scalars(select(User).order_by(User.id)))
        return {"items": [user_list_item(db, user, now) for user in users]}

    @app.get("/admin/users/{user_id}")
    def admin_get_user(
        user_id: int,
        request: Request,
        actor: User = Depends(admin_user),
        db: Session = Depends(get_db),
    ):
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail={"code": "user_not_found"})
        audit(db, request, actor, "admin.user.view", target_user_id=target.id)
        db.commit()
        return {"user": user_payload(target)}

    @app.get("/admin/profiles/{profile_id}")
    def admin_get_profile(profile_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        return {"profile": profile_payload(profile)}

    @app.get("/admin/profiles/{profile_id}/persistent/current/download")
    def admin_download_current(
        profile_id: int,
        request: Request,
        actor: User = Depends(admin_user),
        db: Session = Depends(get_db),
    ):
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        version = require_current_version(db, profile.id)
        audit(db, request, actor, "admin.persistent.current.download", target_user_id=profile.user_id, target_profile_id=profile.id)
        db.commit()
        return StreamingResponse(iter([request.app.state.storage.get(version.object_path)]), media_type="application/octet-stream")

    @app.get("/admin/profiles/{profile_id}/persistent/backups/{backup_id}/download")
    def admin_download_backup(
        profile_id: int,
        backup_id: int,
        request: Request,
        actor: User = Depends(admin_user),
        db: Session = Depends(get_db),
    ):
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        backup = db.scalar(select(PersistentDailyBackup).where(PersistentDailyBackup.id == backup_id, PersistentDailyBackup.profile_id == profile.id))
        if backup is None:
            raise HTTPException(status_code=404, detail={"code": "backup_not_found"})
        version = db.get(PersistentVersion, backup.version_id)
        audit(db, request, actor, "admin.persistent.backup.download", target_user_id=profile.user_id, target_profile_id=profile.id)
        db.commit()
        return StreamingResponse(iter([request.app.state.storage.get(version.object_path)]), media_type="application/octet-stream")

    @app.post("/admin/profiles/{profile_id}/persistent/backups/{backup_id}/restore")
    def admin_restore_backup(
        profile_id: int,
        backup_id: int,
        request: Request,
        actor: User = Depends(admin_user),
        db: Session = Depends(get_db),
    ):
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        version = restore_backup(db, profile.id, backup_id, request_now(request))
        audit(db, request, actor, "admin.persistent.backup.restore", target_user_id=profile.user_id, target_profile_id=profile.id)
        db.commit()
        return version_payload(version)

    def set_ban(
        target_type: str,
        target_id: int,
        reason: str | None,
        request: Request,
        actor: User,
        db: Session,
        action: str,
    ):
        now = request_now(request)
        existing = active_ban(db, target_type, target_id, now)
        if existing is None:
            db.add(Ban(target_type=target_type, target_id=target_id, reason=reason, created_by_admin_user_id=actor.id, created_at=now))
        profile = db.get(Profile, target_id) if target_type in {"profile", "key"} else None
        audit(
            db,
            request,
            actor,
            action,
            target_user_id=target_id if target_type == "user" else profile.user_id if profile else None,
            target_profile_id=target_id if target_type in {"profile", "key"} else None,
            target_profile_key_id=target_id if target_type == "key" else None,
        )
        db.commit()
        return {"status": "banned"}

    def unset_ban(
        target_type: str,
        target_id: int,
        request: Request,
        actor: User,
        db: Session,
        action: str,
    ):
        now = request_now(request)
        for ban in db.scalars(select(Ban).where(Ban.target_type == target_type, Ban.target_id == target_id, Ban.revoked_at.is_(None))):
            ban.revoked_at = now
        profile = db.get(Profile, target_id) if target_type in {"profile", "key"} else None
        audit(
            db,
            request,
            actor,
            action,
            target_user_id=target_id if target_type == "user" else profile.user_id if profile else None,
            target_profile_id=target_id if target_type in {"profile", "key"} else None,
            target_profile_key_id=target_id if target_type == "key" else None,
        )
        db.commit()
        return {"status": "unbanned"}

    @app.post("/admin/users/{user_id}/ban")
    def admin_ban_user(user_id: int, payload: BanRequest, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
        return set_ban("user", user_id, payload.reason, request, actor, db, "admin.user.ban")

    @app.post("/admin/users/{user_id}/unban")
    def admin_unban_user(user_id: int, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
        return unset_ban("user", user_id, request, actor, db, "admin.user.unban")

    @app.post("/admin/profiles/{profile_id}/ban")
    def admin_ban_profile(profile_id: int, payload: BanRequest, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
        return set_ban("profile", profile_id, payload.reason, request, actor, db, "admin.profile.ban")

    @app.post("/admin/profiles/{profile_id}/unban")
    def admin_unban_profile(profile_id: int, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
        return unset_ban("profile", profile_id, request, actor, db, "admin.profile.unban")

    @app.post("/admin/profile-keys/{key_id}/ban")
    def admin_ban_key(key_id: int, payload: BanRequest, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
        return set_ban("key", key_id, payload.reason, request, actor, db, "admin.profile_key.ban")

    @app.post("/admin/profile-keys/{key_id}/unban")
    def admin_unban_key(key_id: int, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
        return unset_ban("key", key_id, request, actor, db, "admin.profile_key.unban")

    @app.post("/admin/profile-keys/{key_id}/refresh")
    def admin_refresh_key(key_id: int, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
        profile = db.get(Profile, key_id)
        if profile is None:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        profile.profile_key_plaintext = generate_profile_key()
        audit(db, request, actor, "admin.profile_key.refresh", target_user_id=profile.user_id, target_profile_id=profile.id, target_profile_key_id=profile.id)
        db.commit()
        return profile_payload(profile)

    @app.post("/admin/profile-keys/{key_id}/revoke")
    def admin_revoke_key(key_id: int, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
        profile = db.get(Profile, key_id)
        if profile is None:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        profile.revoked_at = request_now(request)
        audit(db, request, actor, "admin.profile_key.revoke", target_user_id=profile.user_id, target_profile_id=profile.id, target_profile_key_id=profile.id)
        db.commit()
        return profile_payload(profile)

    @app.post("/admin/locks/{lock_id}/release", status_code=204)
    def admin_release_lock(lock_id: int, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
        lock = db.scalar(select(Lock).where(or_(Lock.id == lock_id, Lock.profile_id == lock_id)))
        target_profile_id = lock.profile_id if lock else lock_id
        if lock:
            db.delete(lock)
        audit(db, request, actor, "admin.lock.release", target_profile_id=target_profile_id)
        db.commit()
        return Response(status_code=204)

    @app.get("/admin/audit-logs")
    def admin_audit_logs(_: User = Depends(admin_user), db: Session = Depends(get_db)):
        logs = list(db.scalars(select(AuditLog).order_by(desc(AuditLog.created_at), desc(AuditLog.id)).limit(200)))
        return {
            "items": [
                {
                    "id": log.id,
                    "actor_user_id": log.actor_user_id,
                    "actor_role": log.actor_role,
                    "action": log.action,
                    "target_user_id": log.target_user_id,
                    "target_profile_id": log.target_profile_id,
                    "target_profile_key_id": log.target_profile_key_id,
                    "ip_address": log.ip_address,
                    "user_agent": log.user_agent,
                    "created_at": log.created_at.isoformat(),
                }
                for log in logs
            ]
        }

    return app


app = create_app
