from __future__ import annotations

from sqlalchemy import text

from app.db import engine


def main() -> None:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
            UPDATE inventory_rows
            SET is_pending = 0
            WHERE is_pending = 1
              AND storage_location_id IN (
                SELECT id FROM storage_locations WHERE type = 'deck'
              )
        """
            )
        )
        print(f"Cleared is_pending on {result.rowcount} deck card rows")


if __name__ == "__main__":
    main()
