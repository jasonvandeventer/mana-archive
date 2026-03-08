import re
import os
from sqlmodel import Session, create_engine, select
from app.models import Card, Inventory

def natural_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]

def fix_order():
    # Use absolute path to ensure the DB is found regardless of execution context
    db_path = os.path.join(os.getcwd(), "data/mana_archive.db")
    engine = create_engine(f"sqlite:///{db_path}")
    
    with Session(engine) as session:
        for d in range(1, 7):
            print(f"Re-indexing Drawer {d} by Collector Number...")
            # Simple select; the relationship handles the data link
            items = session.exec(select(Inventory).where(Inventory.drawer == d)).all()
            
            # Sort in memory using the relationship
            items.sort(key=lambda x: (x.card.set_code, natural_key(x.card.collector_number)))
            
            for idx, item in enumerate(items, start=1):
                item.position = idx
            
        session.commit()
        print("Success: Drawers re-indexed numerically.")

if __name__ == "__main__":
    fix_order()