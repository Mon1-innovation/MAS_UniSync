from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    identification: str
    password: str


class ProfileCreateRequest(BaseModel):
    display_name: str | None = None


class BanRequest(BaseModel):
    reason: str | None = None


class StorageBucketRequest(BaseModel):
    id: int | None = None
    name: str
    type: Literal["local", "webdav"]
    is_active: bool | None = None
    space_budget_bytes: int | None = Field(default=None, ge=0)
    config: dict[str, Any] = Field(default_factory=dict)


class SystemSettingsRequest(BaseModel):
    backend_api_url: str = ""
    frontend_web_url: str = ""
    profile_storage_limit_bytes: int = Field(gt=0)
    max_active_profiles_per_account: int = Field(gt=0)
    active_storage_bucket_id: int | None = None
    storage_buckets: list[StorageBucketRequest] | None = None
