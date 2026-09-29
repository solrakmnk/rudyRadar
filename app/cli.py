import json
from app.database import SessionLocal
from app.sync import sync_all_active_athletes

def main():
    db = SessionLocal()
    try: print(json.dumps(sync_all_active_athletes(db)))
    finally: db.close()
if __name__ == "__main__": main()
