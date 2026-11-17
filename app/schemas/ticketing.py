from datetime import datetime

from pydantic import BaseModel, Field

from .common import Email, Money, Name, ORMModel


class TicketTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    price: Money = Field(description="Montant en euros")
    quantity: int = Field(ge=1, le=1_000_000, description="Nombre limité de billets")


class TicketTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    price: Money | None = None
    quantity: int | None = Field(default=None, ge=1, le=1_000_000)


class TicketTypeRead(ORMModel):
    id: int
    event_id: int
    name: str
    price: float
    quantity: int
    sold: int
    remaining: int


class BuyerInfo(BaseModel):
    first_name: Name
    last_name: Name
    email: Email = Field(description="Identifie l'acheteur : 1 seul billet par personne et par événement")
    street: str = Field(min_length=1, max_length=255)
    postal_code: str = Field(min_length=1, max_length=20)
    city: str = Field(min_length=1, max_length=100)
    country: str = Field(min_length=1, max_length=100)


class TicketPurchase(BuyerInfo):
    pass


class TicketUpdate(BaseModel):
    first_name: Name | None = None
    last_name: Name | None = None
    street: str | None = Field(default=None, min_length=1, max_length=255)
    postal_code: str | None = Field(default=None, min_length=1, max_length=20)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    country: str | None = Field(default=None, min_length=1, max_length=100)


class TicketRead(ORMModel):
    id: int
    event_id: int
    ticket_type_id: int
    first_name: str
    last_name: str
    email: str
    street: str
    postal_code: str
    city: str
    country: str
    purchased_at: datetime
