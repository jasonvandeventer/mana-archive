import pandas as pd
import scrython # Top-level import is most stable
import time
import os
from sqlmodel import Session, create_engine, select
from app.models import Card, Inventory
from app.services.sorter import determine_location

def process_csv(file_path, is_deck=False):
    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/mana_archive.db")
    engine = create_engine(db_url)
    
    df = pd.read_csv(file_path)
    df.columns = df.columns.str.strip().str.lower()

    with Session(engine) as session:
        for _, row in df.iterrows():
            sid = row['scryfall id']
            card = session.exec(select(Card).where(Card.scryfall_id == sid)).first()
            
            # Fix: Always fetch fresh price/data for sorting accuracy
            time.sleep(0.1) 
            try:
                # Use the top-level path to avoid attribute errors
                card_data = scrython.cards.Id(id=sid)
                raw_data = card_data.scryfallJson
                price = float(raw_data.get('prices', {}).get('usd') or 0)
            except Exception as e:
                print(f"Error fetching Scryfall data for {sid}: {e}")
                continue

            if not card:
                card = Card(
                    name=raw_data.get('name'),
                    set_code=raw_data.get('set'),
                    collector_number=str(raw_data.get('collector_number')),
                    scryfall_id=sid,
                    colors=",".join(raw_data.get('colors', [])),
                    cmc=raw_data.get('cmc'),
                    type_line=raw_data.get('type_line'),
                    image_url=raw_data.get('image_uris', {}).get('normal')
                )
                session.add(card)
                session.flush()

            # Fix: Price is now guaranteed to be defined for the sorter
            if is_deck:
                drawer, section = None, "Commander Box"
                loc_type = "Commander Deck"
            else:
                drawer, section = determine_location(price, card.set_code)
                loc_type = "Drawer"

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
        print(f"Successfully processed {file_path}")