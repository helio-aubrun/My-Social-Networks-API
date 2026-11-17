from datetime import datetime

from pydantic import BaseModel, Field

from ..models import GroupType
from .common import ORMModel, Url, UserSummary


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    icon: Url | None = Field(default=None, description="URL de l'icône")
    cover_photo: Url | None = Field(default=None, description="URL de la photo de couverture")
    type: GroupType = Field(default=GroupType.public, description="public, private ou secret")
    allow_member_posts: bool = Field(default=True, description="Les membres peuvent publier")
    allow_member_events: bool = Field(default=True, description="Les membres peuvent créer des événements")
    admin_ids: list[int] = Field(
        default_factory=list, description="Co-administrateurs (le créateur est administrateur d'office)"
    )
    member_ids: list[int] = Field(default_factory=list)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    icon: Url | None = None
    cover_photo: Url | None = None
    type: GroupType | None = None
    allow_member_posts: bool | None = None
    allow_member_events: bool | None = None
    admin_ids: list[int] | None = Field(default=None, min_length=1)
    member_ids: list[int] | None = None


class GroupSummary(ORMModel):
    id: int
    name: str
    type: GroupType
    icon: str | None


class GroupRead(GroupSummary):
    description: str | None
    cover_photo: str | None
    allow_member_posts: bool
    allow_member_events: bool
    admins: list[UserSummary]
    members: list[UserSummary]
    created_at: datetime
    updated_at: datetime
