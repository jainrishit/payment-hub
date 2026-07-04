import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import Base, SessionLocal, engine
from app.services.bank_simulator import simulate_bank_processing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

Base.metadata.create_all(bind=engine)


def main() -> None:
    db = SessionLocal()
    try:
        result = simulate_bank_processing(db)
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()

# Made with Bob
