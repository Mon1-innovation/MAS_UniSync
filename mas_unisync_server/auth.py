from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User


def get_db(request: Request):
    db = request.app.state.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail={"code": "not_authenticated"})
    user = db.scalar(select(User).where(User.id == int(user_id)))
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail={"code": "not_authenticated"})
    return user


def regular_user(user: User = Depends(current_user)) -> User:
    if user.role == "guest":
        raise HTTPException(status_code=403, detail={"code": "guest_account_read_only"})
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail={"code": "admin_required"})
    return user
