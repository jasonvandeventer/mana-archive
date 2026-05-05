"""
Recovery script: delete inventory rows that were incorrectly pulled into the
drawer sorter from deck locations.

Identification: resort TransactionLog entries where source_location is
"drawer=- slot=-" (meaning the row had no drawer assignment and was not
pending — the signature of a card that lived in a deck, not a drawer).

After running this, re-import each deck CSV via the normal import flow
with the correct deck selected as the destination.
"""

from sqlalchemy import text

from app.db import engine


def main() -> None:
    with engine.begin() as conn:
        # Find inventory rows that were deck cards wrongly sorted:
        #   - resort event with source "drawer=- slot=-" (no prior drawer)
        #   - currently sitting in a drawer location and marked pending
        result = conn.execute(
            text(
                """
                SELECT DISTINCT tl.inventory_row_id, c.name, ir.drawer, ir.slot
                FROM transaction_logs tl
                JOIN inventory_rows ir ON tl.inventory_row_id = ir.id
                JOIN cards c ON ir.card_id = c.id
                JOIN storage_locations sl ON ir.storage_location_id = sl.id
                WHERE tl.event_type = 'resort'
                  AND tl.source_location = 'drawer=- slot=-'
                  AND sl.type = 'drawer'
                  AND ir.is_pending = 1
                ORDER BY c.name
            """
            )
        )
        rows = result.fetchall()

        if not rows:
            print("No corrupted deck rows found — nothing to do.")
            return

        print(f"Found {len(rows)} corrupted deck card rows:")
        for row_id, name, drawer, slot in rows:
            print(f"  [{row_id}] {name} (currently drawer={drawer} slot={slot})")

        confirm = input(f"\nDelete these {len(rows)} rows? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

        row_ids = [r[0] for r in rows]
        placeholders = ",".join(str(i) for i in row_ids)

        # Delete transaction log entries first, then the rows
        tl_result = conn.execute(
            text(f"DELETE FROM transaction_logs WHERE inventory_row_id IN ({placeholders})")
        )
        ir_result = conn.execute(text(f"DELETE FROM inventory_rows WHERE id IN ({placeholders})"))

        print(
            f"Deleted {tl_result.rowcount} transaction log entries "
            f"and {ir_result.rowcount} inventory rows."
        )
        print("Done. Re-import each deck CSV via the import flow to restore.")


if __name__ == "__main__":
    main()
