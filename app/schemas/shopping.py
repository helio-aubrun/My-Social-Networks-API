from datetime import datetime

from pydantic import BaseModel, Field

from .common import ORMModel, UserSummary, UTCDateTime


class ShoppingItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200, description="Unique par événement")
    quantity: int = Field(ge=1, le=10_000)
    arrival_time: UTCDateTime = Field(description="Heure d'arrivée à l'événement")


class ShoppingItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: int | None = Field(default=None, ge=1, le=10_000)
    arrival_time: UTCDateTime | None = None


class ShoppingItemRead(ORMModel):
    id: int
    event_id: int
    user: UserSummary
    name: str
    quantity: int
    arrival_time: datetime
    created_at: datetime
