from datetime import datetime

from pydantic import BaseModel, Field

from .common import CommentRead, ORMModel, Url, UserSummary


class AlbumCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class AlbumUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class AlbumRead(ORMModel):
    id: int
    event_id: int
    name: str
    description: str | None
    photo_count: int
    created_at: datetime


class PhotoCreate(BaseModel):
    url: Url
    caption: str | None = None


class PhotoUpdate(BaseModel):
    url: Url | None = None
    caption: str | None = None


class PhotoRead(ORMModel):
    id: int
    album_id: int
    author: UserSummary
    url: str
    caption: str | None
    comments: list[CommentRead]
    created_at: datetime
