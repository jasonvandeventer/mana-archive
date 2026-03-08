import pandas as pd
import requests
import time
import os
import sys
from sqlmodel import Session, create_engine, select
from app.models import Card, Inventory
from app.services.sorter import determine_location

def process_csv(file_path):
    # Log current execution state for DevOps debugging
    print(f"DEBUG: Working Directory: {os.getcwd()}")
    print(f"DEBUG: Attempting to open: {os.path.abspath(file_path)}")

    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/mana_archive.db")
    engine = create_engine(db_url)
    
    if not os.path.exists(file_path):
        print(f"CRITICAL: File not found at {os.path.abspath(file_path)}")
        return

    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        print(f"CRITICAL: Failed to read CSV: {e}")
        return

    df.columns = df.columns.str.strip().str.lower()
    df = df.sort_values(by=['set code', 'name'])
    
    total = len(df)
    print(f"--- Starting Stateful Import: {total} cards ---")

    with Session(engine) as session:
        for index, row in df.iterrows():
            sid = str(row['scryfall id'])
            finish = str(row.get('finish', 'nonfoil')).lower()
            qty = int(row.get('quantity', 1))
            
            time.sleep(0.1) 
            try:
                response = requests.get(f"https://api.scryfall.com/cards/{sid}")
                if response.status_code != 200:
                    print(f"  ! Skip [{index+1}/{total}]: API Error {response.status_code}")
                    continue
                
                raw_data = response.json()
                
                # 1. Finish-Aware Pricing
                prices = raw_data.get('prices', {})
                if 'foil' in finish:
                    price = float(prices.get('usd_foil') or prices.get('usd') or 0)
                elif 'etched' in finish:
                    price = float(prices.get('usd_etched') or prices.get('usd') or 0)
                else:
                    price = float(prices.get('usd') or 0)

                # 2. Multiface Image Support
                uris = raw_data.get('image_uris', {})
                img_url = uris.get('normal') or uris.get('small')
                if not img_url and 'card_faces' in raw_data:
                    img_url = raw_data['card_faces'][0].get('image_uris', {}).get('normal')
                
                card_name = raw_data.get('name')
                set_code = raw_data.get('set').lower()
            except Exception as e:
                print(f"  ! Skip: Connection error. {e}")
                continue

            # 3. Metadata & Idempotency
            card = session.exec(select(Card).where(Card.scryfall_id == sid)).first()
            if not card:
                card = Card(
                    name=card_name, set_code=set_code, scryfall_id=sid,
                    current_price=price, image_url=img_url,
                    collector_number=str(raw_data.get('collector_number')),
                    colors=",".join(raw_data.get('colors', [])),
                    cmc=raw_data.get('cmc'), type_line=raw_data.get('type_line')
                )
                session.add(card)
                session.flush()
            else:
                card.current_price = price
                card.image_url = img_url

            drawer, section = determine_location(price, set_code)
            
            # Check for existing finish in this drawer
            existing_item = session.exec(select(Inventory).where(
                Inventory.card_id == card.id, 
                Inventory.drawer == drawer, 
                Inventory.finish == finish
            )).first()

            if existing_item:
                existing_item.quantity += qty
                print(f"[{index+1}/{total}] Updated {card_name} ({finish})")
            else:
                # 4. Physical Position Logic
                existing_inv = session.exec(
                    select(Inventory).join(Card)
                    .where(Inventory.drawer == drawer)
                    .order_by(Inventory.position)
                ).all()

                insert_pos = 1
                for item in existing_inv:
                    curr_pos = item.position or 0
                    if (item.card.set_code > set_code) or \
                       (item.card.set_code == set_code and item.card.name > card_name):
                        insert_pos = curr_pos
                        break
                    insert_pos = curr_pos + 1

                to_shift = session.exec(
                    select(Inventory).where(Inventory.drawer == drawer, Inventory.position >= insert_pos)
                ).all()
                for item in to_shift:
                    item.position = (item.position or 0) + 1

                session.add(Inventory(
                    card_id=card.id, drawer=drawer, section=section,
                    quantity=qty, position=insert_pos,
                    location_type="Drawer", finish=finish
                ))
                print(f"[{index+1}/{total}] Inserted {card_name} at Pos {insert_pos}")
            
            session.commit()

if __name__ == "__main__":
    # Ensure sys.argv handles module-level input correctly
    if len(sys.argv) > 1:
        # Filter out module path if it appears in argv
        args = [a for a in sys.argv if not a.endswith('.py') and a != '-m']
        csv_file = args[0] if args else "collection.csv"
        process_csv(csv_file)
    else:
        process_csv("collection.csv")