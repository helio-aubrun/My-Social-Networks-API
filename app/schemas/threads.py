from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from .common import CommentRead, ORMModel, Text, UserSummary


class ThreadCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    group_id: int | None = None
    event_id: int | None = None

    @model_validator(mode="after")
    def _single_parent(self):
        if (self.group_id is None) == (self.event_id is None):
            raise ValueError("Un fil de discussion est lié à un groupe OU à un événement (exactement un)")
        return self


class ThreadUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ThreadRead(ORMModel):
    id: int
    title: str | None
    group_id: int | None
    event_id: int | None
    created_at: datetime


class MessageCreate(BaseModel):
    content: Text


class MessageUpdate(BaseModel):
    content: Text


class MessageRead(ORMModel):
    id: int
    thread_id: int
    author: UserSummary
    content: str
    comments: list[CommentRead]
    created_at: datetime
    updated_at: datetime
