from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime


class MaterialBase(BaseModel):
    name: str
    unit: str
    price: float = 0


class MaterialCreate(MaterialBase):
    pass


class MaterialUpdate(BaseModel):
    name: Optional[str] = None
    unit: Optional[str] = None
    price: Optional[float] = None


class Material(MaterialBase):
    id: int
    updated_at: datetime

    class Config:
        from_attributes = True


class ProductionBase(BaseModel):
    date: date
    product_type: str
    quantity: int
    materials_used: Optional[str] = None
    notes: Optional[str] = None


class ProductionCreate(ProductionBase):
    pass


class Production(ProductionBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class SaleBase(BaseModel):
    date: date
    product_type: str
    quantity: int
    unit_price: float
    customer_name: Optional[str] = None
    notes: Optional[str] = None


class SaleCreate(SaleBase):
    pass


class Sale(SaleBase):
    id: int
    total_price: float
    created_at: datetime

    class Config:
        from_attributes = True


class LoginForm(BaseModel):
    username: str
    password: str
