ATTACH DATABASE 'mana_archive.db' AS old;

BEGIN TRANSACTION;

INSERT INTO cards (
    id,
    scryfall_id,
    name,
    set_code,
    set_name,
    collector_number,
    rarity,
    image_url,
    type_line,
    oracle_text,
    price_usd,
    price_usd_foil,
    price_usd_etched,
    updated_at
)
SELECT
    id,
    scryfall_id,
    name,
    set_code,
    set_name,
    collector_number,
    rarity,
    image_uri,
    type_line,
    oracle_text,
    CAST(price_usd AS TEXT),
    CAST(price_usd_foil AS TEXT),
    CAST(price_usd_etched AS TEXT),
    updated_at
FROM old.card;

INSERT INTO inventory_rows (
    id,
    card_id,
    finish,
    quantity,
    drawer,
    slot,
    is_pending,
    notes,
    created_at,
    updated_at
)
SELECT
    i.id,
    i.card_id,
    LOWER(i.finish),
    i.quantity,
    CAST(i.drawer AS TEXT),
    CAST(i.position AS TEXT),
    CASE
        WHEN i.is_placed = 1 THEN 0
        ELSE 1
    END,
    NULLIF(
        TRIM(
            COALESCE(i.location_tag, '') ||
            CASE
                WHEN i.condition IS NOT NULL AND i.condition <> ''
                THEN ' | condition: ' || i.condition
                ELSE ''
            END
        ),
        ''
    ),
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
FROM old.inventory i;

COMMIT;

DETACH DATABASE old;
