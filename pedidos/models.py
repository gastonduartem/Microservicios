from sqlalchemy import Column, Integer, Float, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .db import Base

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    status = Column(String, default="CREATED")   # CREATED | CONFIRMED | CANCELLED
    total_amount = Column(Float, default=0)
    # Asigna automáticamente la fecha/hora actual desde la BD cuando se inserta el registro
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Relación 1 a N con OrderItem, permite acceso bidireccional y elimina ítems huérfanos al borrar el pedido
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, nullable=False)
    qty = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    order = relationship("Order", back_populates="items")
