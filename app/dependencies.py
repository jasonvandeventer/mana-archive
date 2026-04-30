from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import User


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_current_user(session: Session = Depends(get_db_session)) -> User:
    try:
        return session.query(User).filter(User.username == "jason.v").one()
    except NoResultFound as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default development user not found. Run the v3 migration/seed.",
        ) from exc
