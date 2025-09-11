from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = os.getenv("DB_FILE", "productos.db")
DB_PATH = BASE_DIR / DB_FILE

# as_posix: Convierte el Path a un string con formato POSIX (usando / como separador)
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
