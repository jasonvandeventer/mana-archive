from __future__ import annotations

import os
from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import User

# Temporary v3.x development user seam.
#
# Real authentication should replace get_current_user(), not the route/service
# code that already depends on an explicit User object.
DEV_USERNAME = os.getenv("MANA_ARCHIVE_DEV_USER", "jason.v")


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_current_user(session: Session = Depends(get_db_session)) -> User:
    try:
        return session.query(User).filter(User.username == DEV_USERNAME).one()
    except NoResultFound as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Default development user {DEV_USERNAME!r} not found. "
                "Run the v3 migration/seed."
            ),
        ) from exc
