from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from ..models import Visibility
from .common import ORMModel, Url, UserSummary, UTCDateTime


class EventCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200, description="Titre visible par les participants")
    description: str = Field(min_length=1, description="Programme, objectif, infos pratiques…")
    start_date: UTCDateTime
    end_date: UTCDateTime
    location: str = Field(min_length=1, max_length=300, description="Adresse ou lieu")
    cover_photo: Url | None = Field(default=None, description="URL de la photo de couverture")
    visibility: Visibility = Visibility.public
    organizer_ids: list[int] = Field(
        default_factory=list, description="Co-organisateurs (le créateur est organisateur d'office)"
    )
    participant_ids: list[int] = Field(default_factory=list)
    group_id: int | None = Field(default=None, description="Groupe dans lequel l'événement est créé")
    invite_group_members: bool = Field(
        default=True, description="Invite automatiquement tous les membres du groupe"
    )
    ticketing_enabled: bool = Field(default=False, description="Billetterie (événements publics uniquement)")
    shopping_list_enabled: bool = False
    carpool_enabled: bool = False

    @model_validator(mode="after")
    def _check(self):
        if self.end_date <= self.start_date:
            raise ValueError("La date de fin doit être postérieure à la date de début")
        if self.ticketing_enabled and self.visibility != Visibility.public:
            raise ValueError("La billetterie n'est disponible que pour les événements publics")
        return self


class EventUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    start_date: UTCDateTime | None = None
    end_date: UTCDateTime | None = None
    location: str | None = Field(default=None, min_length=1, max_length=300)
    cover_photo: Url | None = None
    visibility: Visibility | None = None
    organizer_ids: list[int] | None = Field(default=None, min_length=1)
    participant_ids: list[int] | None = None
    ticketing_enabled: bool | None = None
    shopping_list_enabled: bool | None = None
    carpool_enabled: bool | None = None


class EventSummary(ORMModel):
    id: int
    name: str
    start_date: datetime
    end_date: datetime
    location: str
    visibility: Visibility
    group_id: int | None


class EventRead(EventSummary):
    description: str
    cover_photo: str | None
    ticketing_enabled: bool
    shopping_list_enabled: bool
    carpool_enabled: bool
    organizers: list[UserSummary]
    participants: list[UserSummary]
    created_at: datetime
    updated_at: datetime


class EventStats(BaseModel):
    event_id: int
    organizers_count: int
    participants_count: int
    messages_count: int
    albums_count: int
    photos_count: int
    polls_count: int
    tickets_sold: int
    tickets_available: int
    ticket_revenue: float
    shopping_items_count: int
    carpool_offers_count: int
    carpool_seats_remaining: int


class ShareLinks(BaseModel):
    event_id: int
    url: str
    links: dict[str, str]
