from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

db_path = DATA_DIR / "mana_archive.db"

if not db_path.exists():
    raise RuntimeError(f"Database not found at {db_path}")

DATABASE_URL = f"sqlite:///{db_path}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)
Base = declarative_base()


def init_db() -> None:
    from app import models  # noqa: F401
    from app.models import User

    Base.metadata.create_all(bind=engine)

    # --- Validation ---
    with SessionLocal() as session:
        # Ensure users table exists and has at least one row
        user_count = session.query(User).count()
        if user_count == 0:
            raise RuntimeError("No users found in database. Migration or seed failed.")


def get_session() -> Session:
    return SessionLocal()
