"""SQLAlchemy models for Mana Archive.

Cards are global reference data. Inventory, decks, imports, audit logs, and
storage locations are user-owned and must be queried through user_id.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    inventory_rows: Mapped[list[InventoryRow]] = relationship(back_populates="user")
    decks: Mapped[list[Deck]] = relationship(back_populates="user")
    import_batches: Mapped[list[ImportBatch]] = relationship(back_populates="user")
    transaction_logs: Mapped[list[TransactionLog]] = relationship(back_populates="user")
    storage_locations: Mapped[list[StorageLocation]] = relationship(back_populates="user")


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    scryfall_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    set_code: Mapped[str] = mapped_column(String(32), index=True)
    set_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    collector_number: Mapped[str] = mapped_column(String(32), index=True)
    rarity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    type_line: Mapped[str | None] = mapped_column(Text, nullable=True)
    oracle_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_usd: Mapped[str | None] = mapped_column(String(32), nullable=True)
    price_usd_foil: Mapped[str | None] = mapped_column(String(32), nullable=True)
    price_usd_etched: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    inventory_rows: Mapped[list[InventoryRow]] = relationship(back_populates="card")
    transaction_logs: Mapped[list[TransactionLog]] = relationship(back_populates="card")


class StorageLocation(Base):
    __tablename__ = "storage_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), index=True)
    type: Mapped[str] = mapped_column(String(64), default="other", index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_locations.id"), nullable=True, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="storage_locations")
    parent: Mapped[StorageLocation | None] = relationship(
        remote_side="StorageLocation.id",
        back_populates="children",
    )
    children: Mapped[list[StorageLocation]] = relationship(back_populates="parent")
    inventory_rows: Mapped[list[InventoryRow]] = relationship(back_populates="storage_location")


class InventoryRow(Base):
    __tablename__ = "inventory_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    storage_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_locations.id"), nullable=True, index=True
    )
    finish: Mapped[str] = mapped_column(String(32), default="normal", index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    drawer: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    slot: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_pending: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="inventory_rows")
    card: Mapped[Card] = relationship(back_populates="inventory_rows")
    storage_location: Mapped[StorageLocation | None] = relationship(back_populates="inventory_rows")


class Deck(Base):
    __tablename__ = "decks"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_decks_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    storage_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_locations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), index=True)
    format: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    storage_location: Mapped[StorageLocation | None] = relationship()
    user: Mapped[User] = relationship(back_populates="decks")


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="import_batches")
    transaction_logs: Mapped[list[TransactionLog]] = relationship(back_populates="batch")


class TransactionLog(Base):
    __tablename__ = "transaction_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id"), nullable=True)
    finish: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quantity_delta: Mapped[int] = mapped_column(Integer, default=0)
    source_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    destination_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id"), nullable=True, index=True
    )
    inventory_row_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="transaction_logs")
    card: Mapped[Card | None] = relationship(back_populates="transaction_logs")
    batch: Mapped[ImportBatch | None] = relationship(back_populates="transaction_logs")
