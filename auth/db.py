from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from pathlib import Path

# __file__ = ruta del archivo, Path() la convierte en objeto Path, resolve() obtiene la ruta absoluta, parent devuelve la carpeta contenedora
BASE_DIR = Path(__file__).resolve().parent 


# Nombre del archivo de la BD (puedes cambiar via .env si querés)
DB_FILE = os.getenv("DB_FILE", "auth.db")  # en productos será "productos.db", etc.

# Ruta ABSOLUTA al archivo dentro del microservicio
DB_PATH = BASE_DIR / DB_FILE
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
