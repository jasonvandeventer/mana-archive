
# Mana-Archive: Installation & Setup Guide

## 1. Environment Setup

Open your terminal on Fedora/Nobara and run:

Bash

```
# Create project structure
mkdir -p mana-archive/{app/scripts,app/ui,app/services,data,imports/archive}
cd mana-archive

# Setup Virtual Environment
python3 -m venv .venv
source .venv/bin/activate

# Install Dependencies
pip install fastapi uvicorn sqlmodel pandas scrython streamlit alembic python-dotenv httpx

```

Create a `.env` file in the root:

Plaintext

```
DATABASE_URL=sqlite:///./data/mana_archive.db

```

----------

## 2. The Data Model (`app/models.py`)

This defines your cards, their physical location (Drawer/Deck), and the metadata for searching.

Python

```
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime

class Card(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    set_code: str = Field(index=True)
    collector_number: str
    scryfall_id: str = Field(unique=True, index=True)
    # Search Metadata
    colors: Optional[str] = None
    cmc: Optional[float] = None
    type_line: Optional[str] = None
    image_url: Optional[str] = None
    
    inventory_items: List["Inventory"] = Relationship(back_populates="card")

class Inventory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    card_id: int = Field(foreign_key="card.id")
    # Location Logic
    location_type: str = "Drawer" # "Drawer" or "Commander Deck"
    drawer: Optional[int] = None
    section: Optional[str] = None
    quantity: int = Field(default=1)
    finish: str = Field(default="nonfoil")
    
    card: Optional[Card] = Relationship(back_populates="inventory_items")

class Price(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    card_id: int = Field(foreign_key="card.id")
    usd_amount: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)

```

----------

## 3. The Sorting Engine (`app/services/sorter.py`)

This implements your specific rules (A-D, E-L, $5+ Value, etc.).

Python

```
def determine_location(price, set_code):
    if price >= 5.0:
        return 3, "High Value"
    
    first_char = set_code[0].upper()
    if not first_char.isalpha():
        return 6, "Numerical/Special"
        
    if first_char in "ABCD": return 1, "A-D"
    if first_char in "EFGHIJKL": return 2, "E-L"
    if first_char in "MNOPQR": return 4, "M-R"
    if first_char in "STUVWXYZ": return 5, "S-Z"
    return 6, "Overflow"

```

----------

## 4. The Import Script (`app/scripts/import_csv.py`)

This handles the TCG Archivist CSV and fetches real-time data from Scryfall.

Python

```
import pandas as pd
import scrython
import time
from sqlmodel import Session, create_engine, select
from app.models import Card, Inventory, Price
from app.services.sorter import determine_location

# Note: Scryfall asks for 100ms delay between requests
def process_csv(file_path, is_deck=False):
    engine = create_engine("sqlite:///./data/mana_archive.db")
    df = pd.read_csv(file_path)
    df.columns = df.columns.str.strip().str.lower()

    with Session(engine) as session:
        for _, row in df.iterrows():
            sid = row['scryfall id']
            
            # 1. Get/Update Card Metadata
            card = session.exec(select(Card).where(Card.scryfall_id == sid)).first()
            if not card:
                # Fetch from Scryfall for metadata & price
                time.sleep(0.1)
                data = scrython.cards.Id(id=sid)
                price = float(data.prices('usd') or 0)
                
                card = Card(
                    name=data.name(),
                    set_code=data.set_code(),
                    collector_number=data.collector_number(),
                    scryfall_id=sid,
                    colors=",".join(data.colors()),
                    cmc=data.cmc(),
                    type_line=data.type_line(),
                    image_url=data.image_uris(0, 'normal')
                )
                session.add(card)
                session.flush()
            
            # 2. Determine Placement
            if is_deck:
                drawer, section = None, "Commander Box"
                loc_type = "Commander Deck"
            else:
                drawer, section = determine_location(price, card.set_code)
                loc_type = "Drawer"

            # 3. Upsert Inventory
            item = session.exec(select(Inventory).where(
                Inventory.card_id == card.id, 
                Inventory.drawer == drawer,
                Inventory.section == section
            )).first()
            
            if item:
                item.quantity += int(row['quantity'])
            else:
                session.add(Inventory(
                    card_id=card.id, drawer=drawer, section=section,
                    quantity=row['quantity'], location_type=loc_type
                ))
        session.commit()

```

----------

## 5. The Grid Dashboard (`app/ui/dashboard.py`)

This creates the visual grid you requested.

Python

```
import streamlit as st
from sqlmodel import Session, create_engine, select
from app.models import Card, Inventory

st.set_page_config(layout="wide")
st.title("Mana-Archive Visual Catalog")

# Search Filters
col1, col2, col3 = st.columns(3)
name_q = col1.text_input("Search Name")
color_q = col2.selectbox("Color", ["All", "W", "U", "B", "R", "G"])
type_q = col3.text_input("Type (e.g. Fungus)")

# Grid Rendering
engine = create_engine("sqlite:///./data/mana_archive.db")
with Session(engine) as session:
    statement = select(Card)
    if name_q: statement = statement.where(Card.name.contains(name_q))
    # ... Add other filters to statement ...
    
    cards = session.exec(statement).all()
    
    rows = [cards[i:i + 6] for i in range(0, len(cards), 6)]
    for row in rows:
        cols = st.columns(6)
        for i, card in enumerate(row):
            with cols[i]:
                st.image(card.image_url)
                st.caption(f"{card.name} | {card.type_line}")
                for inv in card.inventory_items:
                    st.write(f"📍 D{inv.drawer}: {inv.section} (x{inv.quantity})")

```

----------

## 6. Operation Instructions

1.  **Initialize DB**: `alembic revision --autogenerate -m "init" && alembic upgrade head`
    
2.  **Import loose cards**: `python3 -c "from app.scripts.import_csv import process_csv; process_csv('your_scan.csv')"`
    
3.  **Import a Deck**: `python3 -c "from app.scripts.import_csv import process_csv; process_csv('deck.csv', is_deck=True)"`
    
4.  **View Collection**: `streamlit run app/ui/dashboard.py`
