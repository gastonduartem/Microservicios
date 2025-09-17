from sqlalchemy import Column, Integer, String, Boolean, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from .db import Base

# Creamos dos tablas porque productos y stock son conceptos distintos: uno es el catálogo, el otro el inventario, escabilidad

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    size_kg = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True)

    # Esa línea crea una relación 1 a 1 entre Product y Stock, permitiendo navegar en ambos sentidos, relacion 1 a 1. uselist: asegura que product.stock devuelva un único objeto, no una lista
    stock = relationship("Stock", back_populates="product", uselist=False)
    # Esa línea asegura que no puedas tener dos productos con el mismo nombre y tamaño en kilos, manteniendo la integridad de los datos
    __table_args__ = (UniqueConstraint("name", "size_kg", name="uq_name_size"),)

class Stock(Base):
    __tablename__ = "stock"
    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True)
    units_available = Column(Integer, nullable=False, default=0)

    product = relationship("Product", back_populates="stock")
