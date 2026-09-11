import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models

BASE_DIR = Path(__file__).resolve().parent.parent
# On Vercel the filesystem is read-only except /tmp; use /tmp there.
if os.environ.get("VERCEL"):
    DB_PATH = Path("/tmp/payment_hub.db")
else:
    DB_PATH = BASE_DIR / "payment_hub.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

models.Base.metadata.create_all(bind=engine)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=Session,
)
