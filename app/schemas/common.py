import re
from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: str) -> str:
    value = value.strip().lower()
    if not _EMAIL_RE.match(value):
        raise ValueError("Adresse email invalide")
    return value


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _round_money(value: float) -> float:
    return round(value, 2)


Email = Annotated[str, Field(max_length=255), AfterValidator(_validate_email)]
Name = Annotated[str, Field(min_length=1, max_length=100)]
Text = Annotated[str, Field(min_length=1, max_length=5000)]
Url = Annotated[
    str,
    Field(min_length=1, max_length=500, pattern=r"^https?://\S+$", description="URL http(s)"),
]
UTCDateTime = Annotated[datetime, AfterValidator(_to_naive_utc)]
Money = Annotated[float, Field(ge=0, le=1_000_000), AfterValidator(_round_money)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserSummary(ORMModel):
    id: int
    first_name: str
    last_name: str
    email: str


class CommentCreate(BaseModel):
    content: Text


class CommentUpdate(BaseModel):
    content: Text


class CommentRead(ORMModel):
    id: int
    author: UserSummary
    content: str
    created_at: datetime
    updated_at: datetime
