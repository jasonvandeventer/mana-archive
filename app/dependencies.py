from collections.abc import Generator

from fastapi import Depends
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
    return session.query(User).filter(User.username == "jason.v").one()
