from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from jose import jwt, JWTError, ExpiredSignatureError
from typing import Optional
from .db import Base, engine, SessionLocal
from .models import Product, Stock
import os
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

import os, time, requests, hashlib
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

# Cargar SIEMPRE el .env local (no el de la raíz)
ENV_PATH = Path(__file__).resolve().parent / ".env"


load_dotenv(dotenv_path=ENV_PATH, override=True)   # variables al entorno

# Prioriza lo que diga pedidos/.env; si no hay, toma del entorno
SECRET_KEY    = os.getenv("SECRET_KEY")
ALGORITHM     = os.getenv("ALGORITHM", "HS256")
PRODUCTOS_URL = os.getenv("PRODUCTOS_URL", "http://127.0.0.1:8002")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY no está definida en pedidos/.env ni en el entorno")

oauth2_scheme = HTTPBearer()
app = FastAPI(title="Productos Service")


# ---------------- DB init ----------------
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        # # entrega la sesion de la db al endpoint que lo necesite 
        yield db
    finally:
        db.close()

# ---------------- Auth helpers ----------------
class CurrentUser:
    def __init__(self, user_id: int, role: str):
        self.id = user_id
        self.role = role

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)) -> CurrentUser:
    # Aseguramos que sea "Bearer"
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid auth scheme")

    token = credentials.credentials  # <— el JWT puro (sin la palabra Bearer)

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        role = payload.get("role", "user")
        if sub is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return CurrentUser(user_id=int(sub), role=role)
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user

# ---------------- Seeds (solo una vez) ----------------
def seed_products(db: Session):
    # Solo inserta si no hay productos
    if db.query(Product).count() == 0:
        items = [
            {"name": "Hielo Bolsa", "size_kg": 3.0,  "price": 15000, "stock": 100},
            {"name": "Hielo Bolsa", "size_kg": 10.0, "price": 35000, "stock": 50},
            {"name": "Hielo Bolsa", "size_kg": 25.0, "price": 70000, "stock": 20},
        ]
        for it in items:
            p = Product(name=it["name"], size_kg=it["size_kg"], price=it["price"], is_active=True)
            db.add(p); db.flush()  # obtiene p.id sin cerrar la transacción
            s = Stock(product_id=p.id, units_available=it["stock"])
            db.add(s)
        db.commit()

# Ejecuta la semilla solo una vez al arranque del proceso
with SessionLocal() as _db:
    seed_products(_db)

# ---------------- Schemas simples ----------------
def product_to_dict(p: Product):
    return {
        "id": p.id,
        "name": p.name,
        "size_kg": p.size_kg,
        "price": p.price,
        "is_active": p.is_active,
        "units_available": p.stock.units_available if p.stock else 0,
    }

# ---------------- Endpoints (requieren token) ----------------
@app.get("/products")
def list_products(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    products = db.query(Product).filter(Product.is_active == True).all()
    return [product_to_dict(p) for p in products]

@app.get("/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    p = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return product_to_dict(p)

# -------- Admin --------
@app.post("/products", status_code=201)
def create_product(
    name: str, size_kg: float, price: float, initial_stock: int = 0,
    db: Session = Depends(get_db), admin: CurrentUser = Depends(require_admin)
):
    p = Product(name=name, size_kg=size_kg, price=price, is_active=True)
    db.add(p); db.flush()
    db.add(Stock(product_id=p.id, units_available=initial_stock))
    db.commit(); db.refresh(p)
    return product_to_dict(p)

@app.put("/products/{product_id}")
def update_product(
    product_id: int, name: Optional[str] = None, size_kg: Optional[float] = None,
    price: Optional[float] = None, is_active: Optional[bool] = None,
    db: Session = Depends(get_db), admin: CurrentUser = Depends(require_admin)
):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    if name is not None: p.name = name
    if size_kg is not None: p.size_kg = size_kg
    if price is not None: p.price = price
    if is_active is not None: p.is_active = is_active
    db.commit(); db.refresh(p)
    return product_to_dict(p)

@app.patch("/stock/{product_id}/increase")
def increase_stock(product_id: int, amount: int, db: Session = Depends(get_db), admin: CurrentUser = Depends(require_admin)):
    s = db.query(Stock).filter(Stock.product_id == product_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Stock not found")
    s.units_available += max(0, amount)
    db.commit()
    return {"product_id": product_id, "units_available": s.units_available}

@app.patch("/stock/{product_id}/decrease")
def decrease_stock(product_id: int, amount: int, db: Session = Depends(get_db), admin: CurrentUser = Depends(require_admin)):
    s = db.query(Stock).filter(Stock.product_id == product_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Stock not found")
    if amount <= 0 or s.units_available < amount:
        raise HTTPException(status_code=409, detail="Insufficient stock")
    s.units_available -= amount
    db.commit()
    return {"product_id": product_id, "units_available": s.units_available}

# -------- Para Pedidos (verificación de stock) --------
@app.get("/stock/check")
def check_stock(product_id: int, qty: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    if qty <= 0:
        return {"ok": False, "message": "La cantidad debe ser > 0", "product_id": product_id, "requested": qty}

    p = db.query(Product).filter(Product.id == product_id, Product.is_active == True).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")

    s = db.query(Stock).filter(Stock.product_id == product_id).first()
    available = s.units_available if s else 0
    ok = available >= qty

    resp = {
        "ok": ok,
        "product_id": product_id,
        "requested": qty,
        "available": available,
        "price": p.price
    }
    if not ok:
        resp["message"] = f"No hay {qty}, pero hay {available} disponibles."
    else:
        resp["message"] = f"Stock suficiente: {available} disponibles."
    return resp