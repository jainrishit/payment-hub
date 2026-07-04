import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import Base, SessionLocal, engine
from app.services.batch_service import process_end_of_day_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

Base.metadata.create_all(bind=engine)


def main() -> None:
    db = SessionLocal()
    try:
        result = process_end_of_day_batch(db)
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()

# Made with Bob
