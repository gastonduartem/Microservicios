import os,time, requests
from typing import List
from pydantic import BaseModel
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, ExpiredSignatureError
from sqlalchemy.orm import Session
from .db import Base, engine, SessionLocal
from .models import Order, OrderItem
from pathlib import Path
from dotenv import load_dotenv

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
app = FastAPI(title="Pedidos Service")

# ---------- DB init ----------
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- Auth ----------
class CurrentUser:
    def __init__(self, user_id: int, role: str):
        self.id = user_id
        self.role = role

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)) -> CurrentUser:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid auth scheme")
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub  = payload.get("sub")
        role = payload.get("role", "user")
        if sub is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return CurrentUser(user_id=int(sub), role=role)
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except JWTError as e:
        print("JWT decode error (Pedidos):", e)
        raise HTTPException(status_code=401, detail="Invalid token")

# ---------- Schemas ----------
class OrderItemIn(BaseModel):
    product_id: int
    qty: int

class CreateOrderIn(BaseModel):
    items: List[OrderItemIn]

# ---------- Helpers a Productos ----------
def _auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}

def productos_check_stock(token: str, product_id: int, qty: int):
    url = f"{PRODUCTOS_URL}/stock/check"
    try:
        r = requests.get(url, params={"product_id": product_id, "qty": qty},
                         headers=_auth_headers(token), timeout=5)
    except requests.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Productos no responde (check): {e}")
    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="Token inválido para Productos (check)")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Producto {product_id} no existe (check)")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=f"Error en Productos (check): {r.text}")
    return r.json()

def productos_decrease(token: str, product_id: int, amount: int):
    url = f"{PRODUCTOS_URL}/stock/{product_id}/decrease"
    try:
        r = requests.patch(url, params={"amount": amount},
                           headers=_auth_headers(token), timeout=5)
    except requests.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Productos no responde (decrease): {e}")
    return r  # el caller decide qué hacer con el status

def productos_increase(token: str, product_id: int, amount: int):
    url = f"{PRODUCTOS_URL}/stock/{product_id}/increase"
    try:
        return requests.patch(url, params={"amount": amount},
                              headers=_auth_headers(token), timeout=5)
    except requests.RequestException:
        return None  # best-effort

# ---------- Utils ----------
def order_to_dict(o: Order):
    return {
        "id": o.id,
        "status": o.status,
        "total_amount": round(o.total_amount, 2),
        "items": [{"product_id": it.product_id, "qty": it.qty, "unit_price": it.unit_price} for it in o.items],
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }

# ---------- Endpoints utilitarios ----------
@app.get("/health")
def health(): return {"ok": True}

@app.get("/whoami")
def whoami(user: CurrentUser = Depends(get_current_user)):
    return {"id": user.id, "role": user.role}

# ---------- Endpoints de negocio ----------
@app.post("/orders", status_code=201)
def create_order(
    payload: CreateOrderIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
):
    token = credentials.credentials
    if not payload.items:
        raise HTTPException(status_code=400, detail="Pedido vacío")

    # 1) Verificar stock y obtener precios
    enriched = []
    for it in payload.items:
        if it.qty <= 0:
            raise HTTPException(status_code=400, detail="qty debe ser > 0")
        chk = productos_check_stock(token, it.product_id, it.qty)
        if not chk.get("ok", False):
            available = chk.get("available", 0)
            raise HTTPException(status_code=409,
                                detail=f"Sin stock para product_id={it.product_id}: piden {it.qty}, hay {available}.")
        enriched.append((it.product_id, it.qty, float(chk.get("price", 0.0))))

    # 2) Crear orden + items
    order = Order(user_id=user.id, status="CREATED", total_amount=0.0)
    db.add(order); db.flush()

    total = 0.0
    for pid, qty, price in enriched:
        total += price * qty
        db.add(OrderItem(order_id=order.id, product_id=pid, qty=qty, unit_price=price))
    order.total_amount = total
    db.commit(); db.refresh(order)

    # 3) Reservar stock en Productos
    try:
        for pid, qty, _ in enriched:
            r = productos_decrease(token, pid, qty)
            if r.status_code == 409:
                # revertir lo ya reservado
                for pid2, qty2, _ in enriched:
                    if pid2 == pid: break
                    try: productos_increase(token, pid2, qty2)
                    except: pass
                detail = ""
                try: detail = r.json().get("detail", "")
                except: detail = r.text
                raise HTTPException(status_code=409, detail=f"Stock insuficiente (decrease). {detail}")
            if r.status_code == 401:
                raise HTTPException(status_code=401, detail="Token inválido para Productos (decrease)")
            if r.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Producto {pid} no encontrado al reservar")
            if r.status_code >= 400:
                raise HTTPException(status_code=r.status_code, detail=f"Error en Productos (decrease): {r.text}")
    except HTTPException:
        order.status = "CANCELLED"
        db.commit()
        raise

    # 4) Confirmar
    db.commit(); db.refresh(order)
    return order_to_dict(order)

@app.get("/orders")
def list_orders(all: bool = False, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    q = db.query(Order)
    if not (all and user.role == "admin"):
        q = q.filter(Order.user_id == user.id)
    return [order_to_dict(o) for o in q.order_by(Order.created_at.desc()).all()]

@app.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o: raise HTTPException(status_code=404, detail="Order not found")
    if user.role != "admin" and o.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return order_to_dict(o)

@app.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
):
    token = credentials.credentials
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o: raise HTTPException(status_code=404, detail="Order not found")
    if user.role != "admin" and o.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if o.status != "CREATED":
        raise HTTPException(status_code=409, detail=f"No se puede cancelar en estado {o.status}")

    for it in o.items:
        try: productos_increase(token, it.product_id, it.qty)
        except: pass

    o.status = "CANCELLED"
    db.commit(); db.refresh(o)
    return order_to_dict(o)

@app.post("/orders/{order_id}/confirm")
def confirm_order(order_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o: raise HTTPException(status_code=404, detail="Order not found")
    if user.role != "admin" and o.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if o.status != "CREATED":
        raise HTTPException(status_code=409, detail=f"No se puede confirmar en estado {o.status}")
    o.status = "CONFIRMED"
    db.commit(); db.refresh(o)
    return order_to_dict(o)

