from __future__ import annotations

import os
import re
from ipaddress import ip_network
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, Field


DEFAULT_SQLITE_DATABASE_URL = "sqlite:///./data/mas_unisync.db"
DEFAULT_POSTGRES_HOST = "postgres"
DEFAULT_POSTGRES_PORT = "5432"
DEFAULT_POSTGRES_DB = "mas_unisync"
DEFAULT_POSTGRES_USER = "mas_unisync"
SUPPORTED_ENVIRONMENTS = {"test", "development", "production"}


class Settings(BaseModel):
    environment: str = "test"
    database_url: str = DEFAULT_SQLITE_DATABASE_URL
    object_storage_path: Path = Path("./data/objects")
    client_release_cache_path: Path = Path("./data/client-releases")
    session_secret: str = "change-me"
    flarum_url: str = "https://forum.example"
    admin_flarum_group_ids: set[str] = Field(default_factory=set)
    admin_flarum_group_names: set[str] = Field(default_factory=set)
    trusted_proxy_ips: set[str] = Field(default_factory=set)
    lock_ttl_seconds: int = 60


def parse_csv_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in re.split(r"[,，;；]", value) if item.strip()}


def parse_trusted_proxy_ips(value: str | None) -> set[str]:
    trusted_proxy_ips = parse_csv_set(value)
    for item in trusted_proxy_ips:
        try:
            ip_network(item, strict=False)
        except ValueError as exc:
            raise ValueError(f"TRUSTED_PROXY_IPS contains invalid IP or CIDR: {item}") from exc
    return trusted_proxy_ips


def _normalize_environment(value: str | None) -> str:
    environment = (value or "test").strip().lower()
    if environment not in SUPPORTED_ENVIRONMENTS:
        supported = ", ".join(sorted(SUPPORTED_ENVIRONMENTS))
        raise ValueError(f"MAS_UNISYNC_ENV must be one of: {supported}")
    return environment


def _is_postgres_url(database_url: str) -> bool:
    return database_url.startswith(("postgresql://", "postgresql+"))


def _compose_postgres_database_url() -> str:
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise ValueError("POSTGRES_PASSWORD is required when MAS_UNISYNC_ENV=production and DATABASE_URL is unset")

    user = os.getenv("POSTGRES_USER", DEFAULT_POSTGRES_USER)
    host = os.getenv("POSTGRES_HOST", DEFAULT_POSTGRES_HOST)
    port = os.getenv("POSTGRES_PORT", DEFAULT_POSTGRES_PORT)
    database = os.getenv("POSTGRES_DB", DEFAULT_POSTGRES_DB)
    return (
        "postgresql+psycopg://"
        f"{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{quote(database, safe='')}"
    )


def _database_url_for_environment(environment: str) -> str:
    explicit_database_url = os.getenv("DATABASE_URL")
    if explicit_database_url:
        database_url = explicit_database_url
    elif environment == "production":
        database_url = _compose_postgres_database_url()
    else:
        database_url = DEFAULT_SQLITE_DATABASE_URL

    if environment == "production" and not _is_postgres_url(database_url):
        raise ValueError("DATABASE_URL must be a PostgreSQL URL when MAS_UNISYNC_ENV=production")
    return database_url


def build_settings() -> Settings:
    environment = _normalize_environment(os.getenv("MAS_UNISYNC_ENV"))
    return Settings(
        environment=environment,
        database_url=_database_url_for_environment(environment),
        object_storage_path=Path(os.getenv("OBJECT_STORAGE_PATH", "./data/objects")),
        client_release_cache_path=Path(os.getenv("CLIENT_RELEASE_CACHE_PATH", "./data/client-releases")),
        session_secret=os.getenv("SESSION_SECRET", "local-dev-session"),
        flarum_url=os.getenv("FLARUM_URL", "https://forum.example"),
        admin_flarum_group_ids=parse_csv_set(os.getenv("ADMIN_FLARUM_GROUP_IDS")),
        admin_flarum_group_names=parse_csv_set(os.getenv("ADMIN_FLARUM_GROUP_NAMES")),
        trusted_proxy_ips=parse_trusted_proxy_ips(os.getenv("TRUSTED_PROXY_IPS")),
        lock_ttl_seconds=int(os.getenv("LOCK_TTL_SECONDS", "60")),
    )
