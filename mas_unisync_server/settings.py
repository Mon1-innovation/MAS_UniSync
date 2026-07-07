from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    database_url: str = "sqlite:///./data/mas_unisync.db"
    object_storage_path: Path = Path("./data/objects")
    session_secret: str = "change-me"
    flarum_url: str = "https://forum.example"
    admin_flarum_group_ids: set[str] = Field(default_factory=set)
    admin_flarum_group_names: set[str] = Field(default_factory=set)
    lock_ttl_seconds: int = 60

