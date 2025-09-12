from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import jwt, JWTError, ExpiredSignatureError
from typing import List
from pydantic import BaseModel, conint
import requests, time

from db import Base, engine, SessionLocal
from models import Order, OrderItem

# ---------- config ----------
SECRET_KEY = "super_secret_key_123"
ALGORITHM = "HS256"
PRODUCTOS_URL = "http://127.0.0.1:8002"   # endpoint del servicio de productos

oauth2_scheme = HTTPBearer()
app = FastAPI(title="Pedidos Service")

# ---------- DB init ----------
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try: 
        # entrega la sesion de la base de datos al endpoint que lo necesite
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
        sub = payload.get("sub"); role = payload.get("role", "user")
        if sub is None: 
            raise HTTPException(status_code=401, detail="Invalid token")
        return CurrentUser(user_id=int(sub), role=role)
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ---------- Schemas ----------
class OrderItemIn(BaseModel):
    product_id: int
    qty: int

class CreateOrderIn(BaseModel):
    items: List[OrderItemIn]

# ---------- Helpers llamados a Productos ----------
def _auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}

def productos_check_stock(token: str, product_id: int, qty: int):
    url = f"{PRODUCTOS_URL}/stock/check"
    r = requests.get(url, params={"product_id": product_id, "qty": qty}, headers=_auth_headers(token), timeout=5)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Producto {product_id} no existe")
    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="Token inválido para Productos")
    r.raise_for_status()
    return r.json()

def productos_decrease(token: str, product_id: int, amount: int, retries: int = 2, backoff: float = 0.5):
    url = f"{PRODUCTOS_URL}/stock/{product_id}/decrease"
    last = None
    # Esto cubre casos donde el servicio de Productos está lento o falla momentáneamente
    for i in range(retries + 1):
        try:
            # Llama al endpoint de Productos para disminuir stock. Manda el JWT en el header. params agrega amount=<cantidad> a la URL. Timeout de 5 segundos
            r = requests.patch(url, params={"amount": amount}, headers=_auth_headers(token), timeout=5)
            # 200: ok, stock disminuido. 404: producto no existe. 409: conflicto → no hay suficiente stock. 401: token inválido
            if r.status_code in (200, 404, 409, 401):
                return r
            r.raise_for_status()
            return r
        # Si ocurre un error de conexión o timeout, guarda el error y espera un poco antes de reintentar
        except requests.RequestException as e:
            last = e
            time.sleep(backoff * (i + 1))
    raise HTTPException(status_code=503, detail=f"Productos no responde: {last}")

def productos_increase(token: str, product_id: int, amount: int):
    url = f"{PRODUCTOS_URL}/stock/{product_id}/increase"
    return requests.patch(url, params={"amount": amount}, headers=_auth_headers(token), timeout=5)

# ---------- Serializadores ----------
def order_to_dict(o: Order):
    return {
        "id": o.id,
        "status": o.status,
        "total_amount": round(o.total_amount, 2),
        "items": [
            {"product_id": it.product_id, "qty": it.qty, "unit_price": it.unit_price}
            for it in o.items
        ],
        "created_at": o.created_at.isoformat() if o.created_at else None
    }

# ---------- Endpoints ----------
@app.post("/orders", status_code=201)
def create_order(payload: CreateOrderIn, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user),
 credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)):
    token = credentials.credentials
    if not payload.items:
        raise HTTPException(status_code=400, detail="Pedido vacío")

    # 1) verificar stock y traer precios actuales
    # Guardar cada item del pedido pero "enriquecido" con mas info
    enriched = []
    # payload es el body que envió el usuario (CreateOrderIn). items es una lista de OrderItemIn (cada uno tiene product_id y qty)
    for it in payload.items:
        # Hace un GET /stock/check en Productos, pasando product_id y qty.
        chk = productos_check_stock(token, it.product_id, it.qty)
        # Validamos si hay stock suficiente
        if not chk.get("ok", False):
            available = chk.get("available", 0)
            raise HTTPException(status_code=409, detail=f"Sin stock para product_id={it.product_id}: piden {it.qty}, hay {available}.")
        enriched.append((it.product_id, it.qty, float(chk.get("price", 0.0))))

    # 2) crear orden + items
    order = Order(user_id=user.id, status="CREATED", total_amount=0)
    # flush: Empujamos al motor para que tenga id el pedido, pero aun no comiteamos
    db.add(order); db.flush()

    total = 0.0
    for product_id, qty, price in enriched:
        total += price * qty
        db.add(OrderItem(order_id=order.id, product_id=product_id, qty=qty, unit_price=price))
    order.total_amount = total
    # vuelve a leer ese objeto de la DB, para actualizar campos generados automáticamente
    db.commit(); db.refresh(order)

    # 3) reservar stock
    try:
        for product_id, qty, _ in enriched:
            r = productos_decrease(token, product_id, qty)
            if r.status_code == 409:
                # revertir lo reservado previamente
                for pid2, qty2, _ in enriched:
                    if pid2 == product_id: break
                    try: productos_increase(token, pid2, qty2)
                    except: pass
                raise HTTPException(status_code=409, detail=r.json().get("detail", "Stock insuficiente"))
            if r.status_code == 401:
                raise HTTPException(status_code=401, detail="Token inválido para Productos")
            if r.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Producto {product_id} no encontrado al reservar")
    except HTTPException:
        order.status = "CANCELLED"
        db.commit()
        # excepción propia de Python → corta la ejecución del programa
        raise

    # 4) confirmar
    order.status = "CONFIRMED"
    db.commit(); db.refresh(order)
    return order_to_dict(order)

@app.get("/orders")
def list_orders(all: bool = False, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    q = db.query(Order)
    if not (all and user.role == "admin"):
        q = q.filter(Order.user_id == user.id)
    orders = q.order_by(Order.created_at.desc()).all()
    return [order_to_dict(o) for o in orders]

@app.get("/orders/{order_id}")
def get_order(order_id: int,
              db: Session = Depends(get_db),
              user: CurrentUser = Depends(get_current_user)):
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o: raise HTTPException(status_code=404, detail="Order not found")
    if user.role != "admin" and o.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return order_to_dict(o)

@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user), credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)):
    token = credentials.credentials
    o = db.query(Order).filter(Order.id == order_id).first()
    if not o: raise HTTPException(status_code=404, detail="Order not found")
    if user.role != "admin" and o.user_id != o.user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if o.status != "CREATED":
        raise HTTPException(status_code=409, detail=f"No se puede cancelar en estado {o.status}")

    for it in o.items:
        try: productos_increase(token, it.product_id, it.qty)
        except: pass

    o.status = "CANCELLED"
    db.commit(); db.refresh(o)
    return order_to_dict(o)
