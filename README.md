# 🐧 Microservicios - Arquitectura Distribuida

Este proyecto muestra cómo dividir un sistema en **microservicios independientes**, cada uno con su propia lógica y base de datos.  
El objetivo es lograr **escalabilidad, resiliencia** y practicar buenas prácticas de diseño en backend moderno.

![Badge](https://img.shields.io/badge/Python-3.10-blue?logo=python)
![Badge](https://img.shields.io/badge/FastAPI-API-green?logo=fastapi)
![Badge](https://img.shields.io/badge/PostgreSQL-DB-blue?logo=postgresql)

---

## 🚀 Tecnologías principales
- **Python 3**
- **FastAPI**
- **PostgreSQL**
- **JWT** para autenticación y autorización

---

## 📂 Estructura del proyecto
microservicios/
├── auth/ # Servicio de autenticación
├── productos/ # Gestión de productos
└── pedidos/ # Gestión de pedidos

---

## 💡 Características
- Autenticación y autorización con **JWT**.  
- Servicios totalmente independientes.  
- Cada microservicio con **su propia base de datos**.  
- APIs REST documentadas automáticamente con Swagger.  

---

## ▶️ Cómo correr localmente
```bash
# 1. Clonar el repositorio
git clone https://github.com/tuusuario/microservicios.git
cd microservicios

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Correr un servicio (ejemplo: auth)
uvicorn auth.app:app --reload --port 8000

