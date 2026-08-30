import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

logger = logging.getLogger("database")

db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL)

engine_args = {}
if db_url.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}

# Attempt connection to target DB. If it fails, fall back to local SQLite.
try:
    logger.info(f"Attempting connection to Database: {db_url.split('@')[-1] if '@' in db_url else db_url}...")
    engine = create_engine(db_url, **engine_args)
    # Test connection
    with engine.connect() as conn:
        logger.info("Successfully connected to PostgreSQL database.")
except Exception as e:
    logger.warning(f"Database connection failed: {e}. Falling back to local SQLite database...")
    db_url = "sqlite:///./sentinel_gateway.db"
    engine_args = {"connect_args": {"check_same_thread": False}}
    engine = create_engine(db_url, **engine_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
