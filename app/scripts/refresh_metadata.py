import time
import requests
import os
from sqlmodel import Session, create_engine, select
from app.models import Card

def refresh_metadata():
    # Ensure absolute path to DB
    db_path = os.path.join(os.getcwd(), "data/mana_archive.db")
    engine = create_engine(f"sqlite:///{db_path}")
    
    with Session(engine) as session:
        # We target cards where metadata is missing or default
        cards = session.exec(select(Card)).all()
        print(f"Refreshing metadata and prices for {len(cards)} cards...")
        
        for i in range(0, len(cards), 75):
            batch = cards[i:i+75]
            identifiers = [{"id": c.scryfall_id} for c in batch]
            
            try:
                response = requests.post("https://api.scryfall.com/cards/collection", json={"identifiers": identifiers})
                if response.status_code == 200:
                    data = response.json().get('data', [])
                    for card_data in data:
                        db_card = next((c for c in batch if c.scryfall_id == card_data['id']), None)
                        if db_card:
                            # Update Metadata
                            db_card.colors = ",".join(card_data.get('colors', []))
                            db_card.cmc = float(card_data.get('cmc', 0.0))
                            db_card.type_line = card_data.get('type_line', "")
                            
                            # Update Price
                            prices = card_data.get('prices', {})
                            db_card.current_price = float(prices.get('usd') or prices.get('usd_foil') or 0)
                    
                    session.commit()
                    print(f"Hydrated batch {i//75 + 1} (Up to card {min(i+75, len(cards))})")
                else:
                    print(f"Error at batch {i//75}: {response.status_code}")
            except Exception as e:
                print(f"Request failed: {e}")
                
            time.sleep(0.1) # Respect Scryfall's rate limit

if __name__ == "__main__":
    refresh_metadata()