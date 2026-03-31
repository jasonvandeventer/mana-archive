"""
SQLModel data models for Mana-Archive.

A single shared SQLAlchemy MetaData instance is used for ALL models to prevent
the "Multiple classes found for path" error that occurs during Streamlit hot-reloads.

Note: `from __future__ import annotations` is intentionally omitted here.
Enabling it stringifies all annotations, which breaks SQLAlchemy's relationship
resolver on Python 3.10+.
"""
import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import MetaData
from sqlmodel import Field, Relationship, SQLModel

# ---------------------------------------------------------------------------
# Shared metadata registry – prevents duplicate-table errors on hot-reload
# ---------------------------------------------------------------------------
_SHARED_METADATA = MetaData()

SQLModel.metadata = _SHARED_METADATA  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class Finish(str, enum.Enum):
    NONFOIL = "nonfoil"
    FOIL = "foil"
    ETCHED = "etched"


class TransactionKind(str, enum.Enum):
    IMPORT = "import"
    PLACEMENT_CONFIRMED = "placement_confirmed"
    PULL = "pull"
    MOVE = "move"
    QUANTITY_UPDATE = "quantity_update"


DECK_LOCATION = "DECK"
OVERFLOW_DRAWER = 6


# ---------------------------------------------------------------------------
# Card – Scryfall metadata
# ---------------------------------------------------------------------------
class CardBase(SQLModel):
    scryfall_id: str = Field(index=True, unique=True)
    name: str = Field(index=True)
    set_code: str
    set_name: str
    collector_number: str
    rarity: str
    type_line: str
    mana_cost: Optional[str] = None
    cmc: float = 0.0
    colors: Optional[str] = None          # pipe-separated, e.g. "W|U"
    color_identity: Optional[str] = None  # pipe-separated
    image_uri: Optional[str] = None
    price_usd: Optional[float] = None
    price_usd_foil: Optional[float] = None
    oracle_text: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Card(CardBase, table=True):
    __tablename__ = "card"

    id: Optional[int] = Field(default=None, primary_key=True)
    inventory_entries: List["Inventory"] = Relationship(back_populates="card")


class CardRead(CardBase):
    id: int


# ---------------------------------------------------------------------------
# Inventory – Physical placement state
# ---------------------------------------------------------------------------
class InventoryBase(SQLModel):
    card_id: int = Field(foreign_key="card.id", index=True)
    drawer: int = Field(index=True)        # 1-6 or 0 = DECK
    position: int = Field(index=True)     # 1-based ordering within drawer
    quantity: int = 1
    finish: Finish = Finish.NONFOIL
    is_placed: bool = False               # False = pending physical placement
    location_tag: Optional[str] = None   # "DECK:<deck_name>" or None


class Inventory(InventoryBase, table=True):
    __tablename__ = "inventory"

    id: Optional[int] = Field(default=None, primary_key=True)
    card: Optional[Card] = Relationship(back_populates="inventory_entries")


class InventoryRead(InventoryBase):
    id: int
    card: Optional[CardRead] = None


# ---------------------------------------------------------------------------
# TransactionLog – Immutable audit trail
# ---------------------------------------------------------------------------
class TransactionLogBase(SQLModel):
    card_id: int = Field(foreign_key="card.id", index=True)
    inventory_id: Optional[int] = Field(
        default=None,
        sa_column_kwargs={"nullable": True},
        foreign_key="inventory.id",
    )
    kind: TransactionKind
    detail: Optional[str] = None          # Human-readable description
    old_drawer: Optional[int] = None
    new_drawer: Optional[int] = None
    old_position: Optional[int] = None
    new_position: Optional[int] = None
    quantity_delta: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    # Shared UUID for all transactions that belong to the same import batch.
    # None for single-card scans and non-import operations.
    batch_id: Optional[str] = Field(default=None, index=True)


class TransactionLog(TransactionLogBase, table=True):
    __tablename__ = "transaction_log"

    id: Optional[int] = Field(default=None, primary_key=True)


class TransactionLogRead(TransactionLogBase):
    id: int
