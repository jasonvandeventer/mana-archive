from __future__ import annotations

from sqlalchemy import text

from app.db import engine


def table_exists(conn, table: str) -> bool:
    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    ).fetchall()
    return bool(rows)


def main() -> None:
    with engine.begin() as conn:
        if not table_exists(conn, "games"):
            conn.execute(
                text(
                    """
                    CREATE TABLE games (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        played_at DATETIME NOT NULL,
                        format VARCHAR(64),
                        turn_count INTEGER,
                        notes TEXT,
                        created_at DATETIME NOT NULL
                    )
                """
                )
            )
            print("Created games table")
        else:
            print("games table already exists, skipping")

        if not table_exists(conn, "game_seats"):
            conn.execute(
                text(
                    """
                    CREATE TABLE game_seats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        game_id INTEGER NOT NULL REFERENCES games(id),
                        seat_number INTEGER NOT NULL,
                        player_name VARCHAR(128) NOT NULL,
                        deck_id INTEGER REFERENCES decks(id),
                        placement INTEGER,
                        starting_life INTEGER NOT NULL DEFAULT 40,
                        final_life INTEGER
                    )
                """
                )
            )
            print("Created game_seats table")
        else:
            print("game_seats table already exists, skipping")


if __name__ == "__main__":
    main()
