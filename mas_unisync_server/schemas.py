from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    identification: str
    password: str


class ProfileCreateRequest(BaseModel):
    display_name: str | None = None


class BanRequest(BaseModel):
    reason: str | None = None


class SystemSettingsRequest(BaseModel):
    backend_api_url: str = ""
    frontend_web_url: str = ""
    profile_storage_limit_bytes: int = Field(gt=0)
    max_active_profiles_per_account: int = Field(gt=0)
