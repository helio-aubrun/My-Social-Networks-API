from datetime import datetime

from pydantic import BaseModel, Field

from .common import Money, ORMModel, UserSummary, UTCDateTime


class CarpoolCreate(BaseModel):
    departure_location: str = Field(min_length=1, max_length=300)
    departure_time: UTCDateTime
    price: Money = Field(description="Prix proposé par passager")
    seats: int = Field(ge=1, le=8, description="Places disponibles")
    max_detour_minutes: int = Field(ge=0, le=600, description="Temps maximum d'écart accepté (minutes)")


class CarpoolUpdate(BaseModel):
    departure_location: str | None = Field(default=None, min_length=1, max_length=300)
    departure_time: UTCDateTime | None = None
    price: Money | None = None
    seats: int | None = Field(default=None, ge=1, le=8)
    max_detour_minutes: int | None = Field(default=None, ge=0, le=600)


class CarpoolRead(ORMModel):
    id: int
    event_id: int
    driver: UserSummary
    departure_location: str
    departure_time: datetime
    price: float
    seats: int
    remaining_seats: int
    max_detour_minutes: int
    passengers: list[UserSummary]
    created_at: datetime

