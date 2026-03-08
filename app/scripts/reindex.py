from sqlmodel import Session, create_engine, select
from app.models import Card, Inventory

def reindex_drawers():
    engine = create_engine("sqlite:///./data/mana_archive.db")
    with Session(engine) as session:
        for d_num in range(1, 7):
            print(f"Re-indexing Drawer {d_num}...")
            # Fetch all cards in this drawer sorted by Set and Name
            items = session.exec(
                select(Inventory).join(Card)
                .where(Inventory.drawer == d_num)
                .order_by(Card.set_code, Card.name)
            ).all()
            
            for idx, item in enumerate(items, start=1):
                item.position = idx
            
        session.commit()
        print("Done! All drawers are now perfectly alphabetized.")

if __name__ == "__main__":
    reindex_drawers()
