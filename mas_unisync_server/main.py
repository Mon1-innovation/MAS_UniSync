from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, time, timedelta
import secrets

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import String, cast, desc, func, inspect, or_, select, text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .auth import admin_user, current_user, get_db, regular_user
from .database import Base, make_engine, make_sessionmaker
from .flarum import FlarumClient
from .models import AuditLog, Ban, Lock, PersistentDailyBackup, PersistentVersion, Profile, StorageBucket, User
from .services import (
    active_ban,
    active_ban_status,
    active_lock,
    audit,
    aware,
    backup_payload,
    cleanup_expired_locks,
    cleanup_expired_guest_profiles,
    banned_exception,
    ban_for_profile,
    active_profile_count_for_user,
    anonymize_audit_actor,
    delete_storage_bucket,
    delete_profile_key as service_delete_profile_key,
    ensure_default_storage_bucket,
    generate_profile_key,
    get_profile_by_key,
    get_version_bytes,
    max_active_profiles_per_account,
    guest_key_retention_days,
    profile_payload,
    profile_storage_limit_bytes,
    profile_storage_usage,
    projected_profile_storage_usage,
    request_now,
    require_current_version,
    require_lock,
    restore_backup,
    save_system_settings,
    store_upload,
    storage_bucket_usage_payload,
    system_settings_payload,
    test_storage_bucket,
    upsert_flarum_user,
    user_payload,
    utc_now,
    user_storage_usage,
    version_payload,
)
from .schemas import BanRequest, LoginRequest, ProfileCreateRequest, ProfileKeyRequest, ProfileRenameRequest, StorageBucketRequest, SystemSettingsRequest
from .settings import Settings
from .storage import LocalObjectStorage


def ensure_storage_schema(engine) -> None:
    inspector = inspect(engine)
    if "persistent_versions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("persistent_versions")}
    if "bucket_id" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE persistent_versions ADD COLUMN bucket_id INTEGER"))


def run_guest_maintenance(app: FastAPI) -> dict[str, int]:
    with app.state.SessionLocal() as db:
        return cleanup_expired_guest_profiles(db, app.state.settings, utc_now())


async def guest_maintenance_loop(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(24 * 60 * 60)
        await asyncio.to_thread(run_guest_maintenance, app)


def create_app(settings: Settings | None = None, flarum_client=None) -> FastAPI:
    settings = settings or Settings()
    flarum_client = flarum_client or FlarumClient(settings.flarum_url)
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    ensure_storage_schema(engine)
    SessionLocal = make_sessionmaker(engine)
    storage = LocalObjectStorage(settings.object_storage_path)
    with SessionLocal() as db:
        ensure_default_storage_bucket(db, settings)
        db.commit()

    

    

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.to_thread(run_guest_maintenance, app)
        task = asyncio.create_task(guest_maintenance_loop(app))
        app.state.guest_maintenance_task = task
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="MAS UniSync Server", lifespan=lifespan)
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

    @app.post("/login/guest")
    def login_guest(payload: ProfileKeyRequest, request: Request, db: Session = Depends(get_db)):
        now = request_now(request)
        profile = db.scalar(
            select(Profile).where(
                Profile.profile_key_plaintext == payload.profile_key,
                Profile.revoked_at.is_(None),
            )
        )
        if profile is None:
            raise HTTPException(status_code=401, detail={"code": "invalid_profile_key"})
        if profile.user.role != "guest":
            raise HTTPException(status_code=403, detail={"code": "profile_key_not_guest"})
        ban = ban_for_profile(db, profile, now)
        if ban:
            raise banned_exception(ban)
        profile.last_used_at = now
        request.session["user_id"] = profile.user_id
        db.commit()
        return {"user": user_payload(profile.user)}

    @app.post("/logout", status_code=204)
    def logout(request: Request):
        request.session.clear()
        return Response(status_code=204)

    def owned_profile_or_404(db: Session, profile_id: int, user: User) -> Profile:
        profile = db.get(Profile, profile_id)
        if profile is None or profile.user_id != user.id:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        return profile

    def profile_response_payload(db: Session, profile: Profile, now=None) -> dict:
        payload = profile_payload(
            profile,
            profile_storage_usage(db, profile.id),
            profile_storage_limit_bytes(db),
            guest_key_retention_days(db),
        )
        payload["lock_status"] = "active" if now is not None and active_lock(db, profile.id, now) else "none"
        return payload

    @app.get("/v1/config/web-url")
    def get_public_web_url(request: Request, db: Session = Depends(get_db)):
        settings_payload = system_settings_payload(db, request)
        frontend_web_url = settings_payload["frontend_web_url"]
        return {
            "backend_api_url": settings_payload["backend_api_url"],
            "frontend_web_url": frontend_web_url,
            "profile_keys_url": frontend_web_url.rstrip("/") + "/account/profile-keys",
        }

    @app.get("/account/profile-keys")
    def list_profile_keys(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
        now = request_now(request)
        profiles = list(
            db.scalars(select(Profile).where(Profile.user_id == user.id).order_by(Profile.id))
        )
        return {"items": [profile_response_payload(db, profile, now) for profile in profiles]}

    @app.post("/account/profile-keys", status_code=201)
    def create_profile_key(
        payload: ProfileCreateRequest,
        request: Request,
        user: User = Depends(regular_user),
        db: Session = Depends(get_db),
    ):
        active_count = active_profile_count_for_user(db, user.id)
        if active_count >= max_active_profiles_per_account(db):
            raise HTTPException(status_code=409, detail={"code": "active_profile_limit_exceeded"})
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
        return profile_response_payload(db, profile, request_now(request))

    @app.post("/v1/guest/profile-key", status_code=201)
    def create_guest_profile_key(request: Request, db: Session = Depends(get_db)):
        now = request_now(request)
        identity = secrets.token_urlsafe(18)
        user = User(
            flarum_user_id="guest:" + identity,
            username="guest-" + identity,
            display_name="Guest",
            role="guest",
            flarum_groups_json="[]",
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        db.flush()
        profile = Profile(
            user_id=user.id,
            profile_key_plaintext=generate_profile_key(),
            display_name="Guest",
            created_at=now,
            updated_at=now,
        )
        db.add(profile)
        db.flush()
        audit(
            db,
            request,
            None,
            "guest.profile_key.create",
            target_user_id=user.id,
            target_profile_id=profile.id,
            target_profile_key_id=profile.id,
        )
        db.commit()
        return profile_response_payload(db, profile, now)

    @app.post("/account/profile-keys/import-guest")
    def import_guest_profile_key(
        payload: ProfileKeyRequest,
        request: Request,
        user: User = Depends(regular_user),
        db: Session = Depends(get_db),
    ):
        now = request_now(request)
        profile = db.scalar(
            select(Profile)
            .where(
                Profile.profile_key_plaintext == payload.profile_key,
                Profile.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if profile is None:
            raise HTTPException(status_code=404, detail={"code": "invalid_profile_key"})
        ban = ban_for_profile(db, profile, now)
        if ban:
            raise banned_exception(ban)
        guest_owner = profile.user
        if guest_owner.role != "guest":
            created_as_guest = db.scalar(
                select(AuditLog.id).where(
                    AuditLog.action == "guest.profile_key.create",
                    AuditLog.target_profile_id == profile.id,
                )
            )
            code = "guest_profile_already_claimed" if created_as_guest else "profile_key_not_guest"
            raise HTTPException(status_code=409, detail={"code": code})
        if active_profile_count_for_user(db, user.id) >= max_active_profiles_per_account(db):
            raise HTTPException(status_code=409, detail={"code": "active_profile_limit_exceeded"})
        profile.user = user
        profile.user_id = user.id
        profile.updated_at = now
        db.flush()
        audit(
            db,
            request,
            user,
            "guest.profile_key.import",
            target_user_id=user.id,
            target_profile_id=profile.id,
            target_profile_key_id=profile.id,
        )
        anonymize_audit_actor(db, guest_owner.id)
        db.delete(guest_owner)
        db.commit()
        return profile_response_payload(db, profile, now)

    @app.post("/account/profile-keys/{profile_id}/refresh")
    def refresh_profile_key(
        profile_id: int,
        request: Request,
        user: User = Depends(regular_user),
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
        return profile_response_payload(db, profile, request_now(request))

    @app.delete("/account/profile-keys/{profile_id}", status_code=204)
    def delete_account_profile_key(
        profile_id: int,
        request: Request,
        user: User = Depends(regular_user),
        db: Session = Depends(get_db),
    ):
        profile = db.get(Profile, profile_id)
        if profile is None or profile.user_id != user.id:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        service_delete_profile_key(
            db,
            request.app.state.settings,
            request,
            user,
            profile,
            "profile_key.delete",
        )
        return Response(status_code=204)

    @app.get("/account/profiles/{profile_id}")
    def get_account_profile(profile_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
        profile = owned_profile_or_404(db, profile_id, user)
        return {"profile": profile_response_payload(db, profile, request_now(request))}

    @app.patch("/account/profiles/{profile_id}")
    def rename_account_profile(
        profile_id: int,
        payload: ProfileRenameRequest,
        request: Request,
        user: User = Depends(regular_user),
        db: Session = Depends(get_db),
    ):
        profile = owned_profile_or_404(db, profile_id, user)
        display_name = payload.display_name.strip() if payload.display_name is not None else ""
        profile.display_name = display_name or None
        profile.updated_at = request_now(request)
        audit(
            db,
            request,
            user,
            "profile.rename",
            target_user_id=user.id,
            target_profile_id=profile.id,
            target_profile_key_id=profile.id,
        )
        db.commit()
        return profile_response_payload(db, profile, request_now(request))

    @app.post("/account/profiles/{profile_id}/lock/release", status_code=204)
    def release_account_profile_lock(
        profile_id: int,
        request: Request,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        profile = owned_profile_or_404(db, profile_id, user)
        lock = db.scalar(select(Lock).where(Lock.profile_id == profile.id))
        if lock is not None:
            db.delete(lock)
        audit(
            db,
            request,
            user,
            "profile.lock.release",
            target_user_id=user.id,
            target_profile_id=profile.id,
            target_profile_key_id=profile.id,
        )
        db.commit()
        return Response(status_code=204)

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
            iter([get_version_bytes(db, request.app.state.settings, version)]),
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
            iter([get_version_bytes(db, request.app.state.settings, version)]),
            media_type="application/octet-stream",
        )

    @app.post("/account/profiles/{profile_id}/persistent/backups/{backup_id}/restore")
    def account_restore_backup(
        profile_id: int,
        backup_id: int,
        request: Request,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        profile = owned_profile_or_404(db, profile_id, user)
        version = restore_backup(db, profile.id, backup_id, request_now(request))
        audit(db, request, user, "persistent.backup.restore", target_user_id=user.id, target_profile_id=profile.id)
        db.commit()
        return version_payload(version)

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
        return {"profile": profile_response_payload(db, profile, request_now(request))}

    @app.post("/v1/locks/acquire")
    def acquire_lock(
        request: Request,
        db: Session = Depends(get_db),
        profile_key: str | None = Header(default=None, alias="X-MAS-Profile-Key"),
    ):
        now = request_now(request)
        profile = get_profile_by_key(db, profile_key, now)
        settings = request.app.state.settings
        cleanup_expired_locks(db, now)
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
        projected_usage = projected_profile_storage_usage(db, profile.id, now.date(), len(data))
        if projected_usage > profile_storage_limit_bytes(db):
            raise HTTPException(status_code=413, detail={"code": "profile_storage_limit_exceeded"})
        version = store_upload(db, request.app.state.settings, profile, data, renpy_version, mas_version, now)
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
            iter([get_version_bytes(db, request.app.state.settings, version)]),
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

    def pagination(page: int, page_size: int) -> tuple[int, int]:
        if page < 1 or page_size not in {25, 50, 100}:
            raise HTTPException(status_code=422, detail={"code": "invalid_pagination"})
        return page_size, (page - 1) * page_size

    def paged_response(items: list, page: int, page_size: int, has_next: bool) -> dict:
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "has_next": has_next,
        }

    def search_term(q: str | None) -> str | None:
        value = (q or "").strip()[:100]
        return value or None

    def parse_datetime_filter(value: str | None, *, end_of_day: bool = False) -> datetime | None:
        if not value:
            return None
        try:
            if len(value) == 10:
                parsed_date = date.fromisoformat(value)
                return datetime.combine(parsed_date, time.max if end_of_day else time.min)
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_datetime_filter"}) from exc

    @app.get("/admin/users")
    def admin_users(
        request: Request,
        page: int = Query(default=1),
        page_size: int = Query(default=25),
        q: str | None = None,
        sort: str = "id",
        order: str = "asc",
        last_upload_from: str | None = None,
        last_upload_to: str | None = None,
        _: User = Depends(admin_user),
        db: Session = Depends(get_db),
    ):
        if sort not in {"id", "last_upload_at"} or order not in {"asc", "desc"}:
            raise HTTPException(status_code=422, detail={"code": "invalid_sort"})
        limit, offset = pagination(page, page_size)
        now = request_now(request)
        upload_from = parse_datetime_filter(last_upload_from)
        upload_to = parse_datetime_filter(last_upload_to, end_of_day=True)
        last_upload = func.max(Profile.last_upload_at)
        stmt = select(User, last_upload.label("last_upload_at")).outerjoin(Profile, Profile.user_id == User.id).group_by(User.id)
        term = search_term(q)
        if term:
            pattern = f"%{term}%"
            stmt = stmt.where(
                or_(
                    User.username.ilike(pattern),
                    User.display_name.ilike(pattern),
                    cast(User.flarum_user_id, String).ilike(pattern),
                    User.role.ilike(pattern),
                )
            )
        if upload_from is not None:
            stmt = stmt.having(last_upload >= upload_from)
        if upload_to is not None:
            stmt = stmt.having(last_upload <= upload_to)
        if sort == "last_upload_at":
            sort_expr = last_upload
        else:
            sort_expr = User.id
        stmt = stmt.order_by(sort_expr.desc() if order == "desc" else sort_expr.asc(), User.id.asc()).offset(offset).limit(limit + 1)
        rows = db.execute(stmt).all()
        users = [row[0] for row in rows[:limit]]
        return paged_response([user_list_item(db, user, now) for user in users], page, page_size, len(rows) > limit)

    @app.get("/admin/settings")
    def admin_get_settings(request: Request, _: User = Depends(admin_user), db: Session = Depends(get_db)):
        return {"settings": system_settings_payload(db, request)}

    @app.put("/admin/settings")
    def admin_update_settings(
        payload: SystemSettingsRequest,
        request: Request,
        actor: User = Depends(admin_user),
        db: Session = Depends(get_db),
    ):
        settings_payload = save_system_settings(db, request, payload)
        audit(db, request, actor, "admin.settings.update")
        db.commit()
        return {"settings": settings_payload}

    @app.post("/admin/storage-buckets/test")
    def admin_test_storage_bucket(
        payload: StorageBucketRequest,
        request: Request,
        _: User = Depends(admin_user),
        db: Session = Depends(get_db),
    ):
        test_storage_bucket(db, request.app.state.settings, payload)
        return {"status": "ok"}

    @app.get("/admin/storage-buckets/{bucket_id}/usage")
    def admin_storage_bucket_usage(
        bucket_id: int,
        _: User = Depends(admin_user),
        db: Session = Depends(get_db),
    ):
        bucket = db.get(StorageBucket, bucket_id)
        if bucket is None:
            raise HTTPException(status_code=404, detail={"code": "storage_bucket_not_found"})
        return storage_bucket_usage_payload(db, bucket)

    @app.delete("/admin/storage-buckets/{bucket_id}")
    def admin_delete_storage_bucket(
        bucket_id: int,
        request: Request,
        confirm: bool = False,
        actor: User = Depends(admin_user),
        db: Session = Depends(get_db),
    ):
        if not confirm:
            raise HTTPException(status_code=400, detail={"code": "storage_bucket_delete_confirmation_required"})
        summary = delete_storage_bucket(db, request.app.state.settings, bucket_id)
        audit(db, request, actor, "admin.storage_bucket.delete")
        db.commit()
        return summary

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
        profiles = list(db.scalars(select(Profile).where(Profile.user_id == target.id).order_by(Profile.id)))
        audit(db, request, actor, "admin.user.view", target_user_id=target.id)
        db.commit()
        return {
            "user": user_payload(target),
            "profiles": [profile_response_payload(db, profile, request_now(request)) for profile in profiles],
        }

    @app.get("/admin/profiles/{profile_id}")
    def admin_get_profile(profile_id: int, request: Request, _: User = Depends(admin_user), db: Session = Depends(get_db)):
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        return {"profile": profile_response_payload(db, profile, request_now(request))}

    @app.get("/admin/profiles/{profile_id}/persistent/current")
    def admin_persistent_current(profile_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        return version_payload(require_current_version(db, profile.id))

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
        return StreamingResponse(
            iter([get_version_bytes(db, request.app.state.settings, version)]),
            media_type="application/octet-stream",
        )

    @app.get("/admin/profiles/{profile_id}/persistent/backups")
    def admin_list_backups(profile_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        rows = db.execute(
            select(PersistentDailyBackup, PersistentVersion)
            .join(PersistentVersion, PersistentVersion.id == PersistentDailyBackup.version_id)
            .where(PersistentDailyBackup.profile_id == profile.id)
            .order_by(desc(PersistentDailyBackup.backup_date))
        ).all()
        return {"items": [backup_payload(backup, version) for backup, version in rows]}

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
        return StreamingResponse(
            iter([get_version_bytes(db, request.app.state.settings, version)]),
            media_type="application/octet-stream",
        )

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
        return profile_response_payload(db, profile, request_now(request))

    @app.delete("/admin/profile-keys/{key_id}", status_code=204)
    def admin_delete_key(key_id: int, request: Request, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
        profile = db.get(Profile, key_id)
        if profile is None:
            raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
        service_delete_profile_key(
            db,
            request.app.state.settings,
            request,
            actor,
            profile,
            "admin.profile_key.delete",
        )
        return Response(status_code=204)

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
    def admin_audit_logs(
        page: int = Query(default=1),
        page_size: int = Query(default=25),
        q: str | None = None,
        _: User = Depends(admin_user),
        db: Session = Depends(get_db),
    ):
        limit, offset = pagination(page, page_size)
        stmt = select(AuditLog)
        term = search_term(q)
        if term:
            pattern = f"%{term}%"
            stmt = stmt.where(
                or_(
                    AuditLog.action.ilike(pattern),
                    AuditLog.actor_role.ilike(pattern),
                    cast(AuditLog.actor_user_id, String).ilike(pattern),
                    cast(AuditLog.target_user_id, String).ilike(pattern),
                    cast(AuditLog.target_profile_id, String).ilike(pattern),
                    cast(AuditLog.target_profile_key_id, String).ilike(pattern),
                    AuditLog.ip_address.ilike(pattern),
                    AuditLog.user_agent.ilike(pattern),
                )
            )
        logs = list(db.scalars(stmt.order_by(desc(AuditLog.created_at), desc(AuditLog.id)).offset(offset).limit(limit + 1)))
        return paged_response(
            [
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
                for log in logs[:limit]
            ],
            page,
            page_size,
            len(logs) > limit,
        )


    return app


app = create_app













