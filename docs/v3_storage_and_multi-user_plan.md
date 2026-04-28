# Mana Archive v3.0.0 — Storage Locations & Multi-User Architecture

## 1. Purpose

Transition Mana Archive from a single-user, drawer-specific inventory tool into a flexible, multi-user collection system where each user defines their own storage model.

This version introduces:

- User accounts
- Flexible storage locations
- Unified collection view across all locations

---

## 2. Current Limitations (v2.x)

### Storage Model

- Hardcoded to "drawer + slot"
- Only supports one storage paradigm
- Decks exist outside the main inventory model

### Deck System

- Decks are not true storage locations
- Cards are "pulled" from collection instead of existing in a location

### Multi-User

- No user separation
- All data is global
- Unsafe for shared usage

---

## 3. Target Architecture

### Core Concept: StorageLocation

All physical or logical locations become first-class entities.

Examples:

- Drawer 1
- Drawer 2
- Deck: Wilhelt Zombies
- Binder: Trade Binder
- Box: Bulk
- Pending

---

## 4. Data Model Changes

### New Table: StorageLocation

Fields:

- id
- name (e.g. "Drawer 1", "Wilhelt Deck")
- type (drawer, deck, binder, box, pending, custom)
- user_id
- sort_order (optional)

---

### Updated: InventoryRow

Replace:

- drawer
- slot

With:

- location_id (FK → StorageLocation)
- position (string, replaces slot)
- is_pending (may be derived or removed later)

---

### Updated: Deck

Options:

- Either remove Deck table entirely
- Or convert it into a wrapper over StorageLocation (type="deck")

Recommended:

- Keep Deck as metadata, but link to StorageLocation

---

### New Table: User

Fields:

- id
- username
- password_hash
- created_at

---

## 5. Migration Plan

### Step 1 — Introduce User

- Create default user for existing data
- Assign all existing records to that user

### Step 2 — Create StorageLocation

- Convert drawers into locations:
  - "Drawer 1" → type=drawer
  - ...

- Create:
  - "Pending" location

### Step 3 — Migrate Inventory

- Map:
  - drawer → location_id
  - slot → position

### Step 4 — Convert Decks

- For each deck:
  - Create StorageLocation with type="deck"
  - Move DeckItems into InventoryRow entries tied to that location

### Step 5 — Remove old fields

- Remove drawer and slot columns after migration is stable

---

## 6. Application Behavior Changes

### Collection Page

Now shows:

- All owned cards
- Across ALL locations

Columns:

- Card
- Quantity
- Finish
- Location (Drawer, Deck, Binder, etc.)
- Position

---

### Decks

Decks become:

- Storage locations of type "deck"

Behavior:

- No sorting
- No pending unless explicitly moved
- Cards remain owned even if not in main drawers

---

### Moving Cards

New flows:

- Move between locations
- Assign to deck directly
- Move from deck → pending or drawer

---

## 7. Multi-User Behavior

Each user:

- Has their own StorageLocations
- Has their own InventoryRows
- Cannot see other users’ data

---

## 8. Authentication (MVP)

- Login page
- Session-based auth
- No roles/permissions yet

---

## 9. UI Changes

- Replace "Drawer" terminology with "Location"
- Add location filters to Collection
- Add "Move to Location" actions
- Add "Create Location" UI

---

## 10. Testing Checklist

Before playgroup testing:

- [ ] Users cannot see each other's data
- [ ] Locations are user-specific
- [ ] Collection shows correct location for all cards
- [ ] Decks behave like storage locations
- [ ] Moving cards updates location correctly
- [ ] Migration preserves all existing data

---

## 11. Risks

- Data migration errors
- Breaking existing workflows
- Mixing old and new models during transition

Mitigation:

- Backup DB before migration
- Test migration locally with real data

---

## 12. Definition of Done

v3.0.0 is complete when:

- Users can log in
- Users can define their own storage locations
- Decks function as locations
- Collection reflects all owned cards with accurate locations
- No drawer-specific assumptions remain in the system
