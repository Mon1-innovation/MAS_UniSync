from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    identification: str
    password: str


class ProfileCreateRequest(BaseModel):
    display_name: str | None = None


class BanRequest(BaseModel):
    reason: str | None = None
