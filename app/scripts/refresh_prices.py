import time
import requests
from sqlmodel import Session, create_engine, select
from app.models import Card

def refresh_prices():
    engine = create_engine("sqlite:///./data/mana_archive.db")
    with Session(engine) as session:
        cards = session.exec(select(Card)).all()
        print(f"Refreshing prices for {len(cards)} unique cards...")
        
        # Process in batches of 75 (Scryfall API limit for collection endpoint)
        for i in range(0, len(cards), 75):
            batch = cards[i:i+75]
            identifiers = [{"id": c.scryfall_id} for c in batch]
            
            response = requests.post("https://api.scryfall.com/cards/collection", json={"identifiers": identifiers})
            if response.status_code == 200:
                data = response.json().get('data', [])
                for card_data in data:
                    # Match by UUID
                    db_card = next((c for c in batch if c.scryfall_id == card_data['id']), None)
                    if db_card:
                        # Logic: Use foil price if available/relevant, else nonfoil
                        prices = card_data.get('prices', {})
                        new_price = float(prices.get('usd') or prices.get('usd_foil') or 0)
                        db_card.current_price = new_price
                session.commit()
                print(f"Updated batch {i//75 + 1}")
            time.sleep(0.1) # Respect API rate limits

if __name__ == "__main__":
    refresh_prices()