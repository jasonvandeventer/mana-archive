from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime

class Card(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    set_code: str = Field(index=True)
    collector_number: str
    scryfall_id: str = Field(unique=True, index=True)
    colors: Optional[str] = None
    cmc: Optional[float] = None
    type_line: Optional[str] = None
    image_url: Optional[str] = None
    current_price: Optional[float] = Field(default=0.0)
    
    inventory_items: List["Inventory"] = Relationship(back_populates="card")

class Inventory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    card_id: int = Field(foreign_key="card.id")
    location_type: str = "Drawer" 
    drawer: Optional[int] = None
    section: Optional[str] = None
    position: Optional[int] = Field(default=None, index=True)
    quantity: int = Field(default=1)
    finish: str = Field(default="nonfoil")
    
    card: Optional[Card] = Relationship(back_populates="inventory_items")

class Price(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    card_id: int = Field(foreign_key="card.id")
    usd_amount: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)