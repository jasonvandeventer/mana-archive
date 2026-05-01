from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import User


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    request: Request,
    session: Session = Depends(get_db_session),
) -> User:
    user_id = request.session.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Redirect to login",
            headers={"Location": "/login"},
        )

    user = session.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive",
        )

    return user
