from __future__ import annotations

from sqlalchemy import text

from app.db import engine


def column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def main() -> None:
    print(f"Using database: {engine.url}")

    with engine.begin() as conn:
        if not column_exists(conn, "decks", "storage_location_id"):
            print("Adding decks.storage_location_id")
            conn.execute(text("ALTER TABLE decks ADD COLUMN storage_location_id INTEGER"))
        else:
            print("decks.storage_location_id already exists")

        decks = conn.execute(
            text(
                """
                SELECT id, user_id, name, storage_location_id
                FROM decks
                ORDER BY id
                """
            )
        ).fetchall()

        print(f"Found decks: {len(decks)}")

        for deck in decks:
            deck_id = deck[0]
            user_id = deck[1]
            deck_name = deck[2]
            storage_location_id = deck[3]

            if storage_location_id is None:
                existing_location = conn.execute(
                    text(
                        """
                        SELECT id
                        FROM storage_locations
                        WHERE user_id = :user_id
                          AND name = :name
                          AND type = 'deck'
                        LIMIT 1
                        """
                    ),
                    {"user_id": user_id, "name": deck_name},
                ).fetchone()

                if existing_location:
                    location_id = existing_location[0]
                    print(f"Reusing deck location {location_id} for deck {deck_id}: {deck_name}")
                else:
                    result = conn.execute(
                        text(
                            """
                            INSERT INTO storage_locations
                                (user_id, name, type, parent_id, sort_order, created_at)
                            VALUES
                                (:user_id, :name, 'deck', NULL, 0, CURRENT_TIMESTAMP)
                            """
                        ),
                        {"user_id": user_id, "name": deck_name},
                    )
                    location_id = result.lastrowid
                    print(f"Created deck location {location_id} for deck {deck_id}: {deck_name}")

                conn.execute(
                    text(
                        """
                        UPDATE decks
                        SET storage_location_id = :location_id
                        WHERE id = :deck_id
                        """
                    ),
                    {"location_id": location_id, "deck_id": deck_id},
                )
            else:
                location_id = storage_location_id

            deck_items = conn.execute(
                text(
                    """
                    SELECT card_id, finish, quantity
                    FROM deck_items
                    WHERE deck_id = :deck_id
                    """
                ),
                {"deck_id": deck_id},
            ).fetchall()

            for card_id, finish, quantity in deck_items:
                existing_row = conn.execute(
                    text(
                        """
                        SELECT id, quantity
                        FROM inventory_rows
                        WHERE user_id = :user_id
                          AND card_id = :card_id
                          AND finish = :finish
                          AND storage_location_id = :location_id
                          AND is_pending = 0
                        LIMIT 1
                        """
                    ),
                    {
                        "user_id": user_id,
                        "card_id": card_id,
                        "finish": finish,
                        "location_id": location_id,
                    },
                ).fetchone()

                if existing_row:
                    conn.execute(
                        text(
                            """
                            UPDATE inventory_rows
                            SET quantity = quantity + :quantity,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = :row_id
                            """
                        ),
                        {"quantity": quantity, "row_id": existing_row[0]},
                    )
                else:
                    conn.execute(
                        text(
                            """
                            INSERT INTO inventory_rows
                                (
                                    user_id,
                                    card_id,
                                    storage_location_id,
                                    finish,
                                    quantity,
                                    drawer,
                                    slot,
                                    is_pending,
                                    notes,
                                    created_at,
                                    updated_at
                                )
                            VALUES
                                (
                                    :user_id,
                                    :card_id,
                                    :location_id,
                                    :finish,
                                    :quantity,
                                    NULL,
                                    NULL,
                                    0,
                                    NULL,
                                    CURRENT_TIMESTAMP,
                                    CURRENT_TIMESTAMP
                                )
                            """
                        ),
                        {
                            "user_id": user_id,
                            "card_id": card_id,
                            "location_id": location_id,
                            "finish": finish,
                            "quantity": quantity,
                        },
                    )

            if deck_items:
                conn.execute(
                    text(
                        """
                        DELETE FROM deck_items
                        WHERE deck_id = :deck_id
                        """
                    ),
                    {"deck_id": deck_id},
                )
                print(f"Deleted migrated deck_items for deck {deck_id}: {len(deck_items)}")

        missing = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM decks
                WHERE storage_location_id IS NULL
                """
            )
        ).scalar_one()

        if missing:
            raise RuntimeError(f"Decks missing storage_location_id: {missing}")

        print("Migration validation passed.")
        print("Migration complete.")


if __name__ == "__main__":
    main()
