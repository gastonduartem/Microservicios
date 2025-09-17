# Crear la app, definir rutas y manejar peticiones y respuestas de manera automatica | Te deja reutilizar lógica, (ej: autenticación, conexión a BD, validación) en múltiples endpoints | Es la forma estándar de lanzar errores HTTP en FastAPI
from fastapi import FastAPI, Depends, HTTPException
# Extrae el token del header Authorization, Si no hay token, lanza automáticamente un 401 Unauthorized, para proteger endpoints y leer el token JWT | Permite leer automáticamente los campos username y password del form-data enviado en el request, Así no tenés que parsear el body vos a mano, para recibir usuario/clave en el login
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
# Este es un tipo de excepción, Lo usás para capturar errores cuando intentás decodificar/verificar un token, excepción que salta si el token está mal (caducado, manipulado, inválido) | Sirve para crear y verificar tokens JWT, librería para generar y verificar tokens
from jose import JWTError, jwt
# es la herramienta para manejar hashing y verificación de contraseñas
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from .db import Base, engine, SessionLocal
from .models import User
import os

import os, time, requests, hashlib
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

# Cargar SIEMPRE el .env local (no el de la raíz)
ENV_PATH = Path(__file__).resolve().parent / ".env"
print("[PEDIDOS] .env path:", ENV_PATH, "exists:", ENV_PATH.exists())

load_dotenv(dotenv_path=ENV_PATH, override=True)   # variables al entorno


# Busca la secret key en mi archivo, si no utiliza el changeme por defecto
SECRET_KEY = os.getenv("SECRET_KEY", "changeme")
# lo mismo que el de arriba. Define como se firma el token
ALGORITHM = os.getenv("ALGORITHM", "HS256")
# define cuanto tiempo dura un token antes de expirar
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY no está definida en pedidos/.env ni en el entorno")

# Diagnóstico: longitud y bytes iniciales (no imprime la clave en claro)
print(
    "[SERVICE] PEDIDOS",
    "KEY:", hashlib.sha256(SECRET_KEY.encode()).hexdigest()[:12],
    "LEN:", len(SECRET_KEY),
    "BYTES0-4:", list(SECRET_KEY.encode()[:5]),
    "ALG:", ALGORITHM
)



# Crea el hashing de las contraseñas | usa bcrypt como algoritmo de hashing | Si en algún momento definís varios algoritmos en schemes, Automáticamente marcará como "deprecados" los que no sean el primero, podés migrar contraseñas viejas a un algoritmo más seguro cuando los usuarios vuelvan a loguearse
password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# Le dice a FastApi que el endpoint /login es el que le entrega el token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

app = FastAPI(title="Auth Service")

# --- DB setup ---
Base.metadata.create_all(bind=engine)

# --- Funciones adicionales ---
def get_db():
    db = SessionLocal()
    try:
        # entrega la sesion de la db al endpoint que lo necesite
        yield db
    finally:
        db.close()

# sirve para comprobar si la contraseña ingresada en el login coincide con el hash guardado en la base de datos
def verify_password(plain, hashed):
    return password_context.verify(plain, hashed)

# sirve para hashear la contraseña
def hash_password(password):
    return password_context.hash(password)

# Generamos un JWT firmado con la secret key, dentro guarda el usuario y la expiracion
def create_access_token(data: dict, expires_delta: timedelta = None):
    # Hace una copia de lq se va a codificar
    to_encode = data.copy()
    # Se ve cuando expira el token o si no utiliza 15min por defecto
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    # Retorno todos esos datos codificados
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# Obtiene el usuario a partir del token
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        # decodifica usanod la secret key y el algoritmo configurado
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # Obtiene el usuario
        user_id: int = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    # busca en la base de datos el nombre del usuario
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# --- Endpoints ---

# Endpoint para registrar nuevos usuarios
@app.post("/register")
def register(email: str, password: str, role: str = "user", db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = User(email=email, password_hash=hash_password(password), role=role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"msg": "User created", "user_id": new_user.id}

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Busca al usuario en la base de datos
    user = db.query(User).filter(User.email == form_data.username).first()
    # Verifica credenciales
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # Crea el JWT
    token = create_access_token(
        data={"sub": str(user.id), "role": user.role},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": token, "token_type": "bearer"}

@app.get("/me")
# Devuelve los datos del usuario actualmente logueado
def read_me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email, "role": current_user.role}
