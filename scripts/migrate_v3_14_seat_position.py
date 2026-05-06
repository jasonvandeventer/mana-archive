"""Add grid_position column to game_seats for fixed 8-seat topology."""

from __future__ import annotations

from sqlalchemy import text

from app.db import engine


def column_exists(conn, table: str, col: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == col for r in rows)


def main() -> None:
    with engine.begin() as conn:
        if not column_exists(conn, "game_seats", "grid_position"):
            conn.execute(text("ALTER TABLE game_seats ADD COLUMN grid_position TEXT"))
