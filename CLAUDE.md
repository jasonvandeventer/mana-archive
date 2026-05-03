# Mana Archive — Claude Context

## Current version: v3.4.5

## Stack: FastAPI + Jinja2 + SQLite + K3s/ArgoCD

## Non-negotiable constraints

- InventoryRow is the single source of truth
- StorageLocation is the canonical location system (decks = type="deck")
- SQLite until v4 — do NOT suggest PostgreSQL changes
- No service layers unless already present
- Do NOT break existing routes or templates (live system)

## Current phase

Post-release validation. Optimize for usability, not features.

## Telemetry query

kubectl exec -n mana-archive deploy/mana-archive -- \
python -c "from sqlalchemy import text; from app.db import engine; \
conn = engine.connect(); \
rows = conn.execute(text('''
SELECT u.username,
COUNT(DISTINCT ir.id) as inventory_rows,
COUNT(DISTINCT d.id) as decks
FROM users u
LEFT JOIN inventory_rows ir ON u.id = ir.user_id
LEFT JOIN decks d ON u.id = d.user_id
GROUP BY u.username
ORDER BY inventory_rows DESC
''')).fetchall(); \
print('\n'.join(str(r) for r in rows)); conn.close()"

## Roadmap

- v3.5: Remove DeckItem, simplify model
- v3.6: Import framework
- v4.0: PostgreSQL migration
