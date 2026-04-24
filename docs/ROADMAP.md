# Mana Archive Roadmap

## Phase 1 — Data Integrity & Core UX (Current Focus)

### 1. Enhanced Pending View

* Show: FROM → TO (previous location → new location)
* Source: TransactionLog
* Purpose: eliminate ambiguity during relocation

### 2. Set Completion / Missing Cards (v2.2.0)

* Route: /sets/<set_code>
* Show:

  * Owned vs Missing count
  * Completion %
* Missing list sorted by collector number
* Source: Scryfall set data vs inventory

### 3. Drawer Audit Mode (Lightweight)

* Show expected count vs physical count
* Allow marking drawer as verified
* Purpose: prevent silent drift

---

## Phase 2 — Collection Intelligence

### 4. Duplicate Detection

* Identify excess copies
* Surface trade/sell candidates

### 5. Value Insights

* Total collection value
* Value by drawer
* Value by set
* Top valuable cards

### 6. Upgrade Suggestions

* Highlight near-complete sets
* Suggest low-cost missing cards

---

## Phase 3 — Deck Integration

### 7. Deck ↔ Inventory Linking

* Show if owned
* Show physical location

### 8. Buildable Deck Detection

* “You can build this”
* “Missing X cards”

### 9. Deck Import

* Import from Moxfield / EDHREC
* Match against inventory

---

## Phase 4 — Operational Maturity

### 10. Audit Log UI

* Filter by card, drawer, event type
* Visualize movement history

### 11. Backup / Restore UX

* Trigger backup
* Restore snapshot

### 12. Bulk Operations

* Bulk confirm pending
* Bulk move/delete

---

## Phase 5 — Product-Level Features

### 13. Multi-User Support

* Single app, multiple users
* Data scoped by user_id
* Shared card metadata
* Auth via OAuth/OIDC (preferred)

### 14. Barcode / Camera Scanning

* Mobile-friendly input

### 15. Public Collection View

* Shareable collection pages

---

## Guiding Principles

* Data integrity > features
* One source of truth: physical collection
* Every feature must improve:

  * clarity
  * correctness
  * usability

---

## Immediate Next Steps

1. Finish rebuild
2. Enhanced Pending View
3. Tag release
4. Set Completion feature
5. Observability stack (Prometheus / Grafana / Loki)

