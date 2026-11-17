from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from ..models import Role
from ..security import PASSWORD_RULE, validate_password_strength
from .common import Email, Name, Url, UserSummary

Password = Annotated[
    str, Field(min_length=8, max_length=72, description=PASSWORD_RULE), AfterValidator(validate_password_strength)
]


class UserBase(BaseModel):
    first_name: Name
    last_name: Name
    email: Email
    bio: str | None = Field(default=None, max_length=2000)
    avatar_url: Url | None = None


class UserCreate(UserBase):
    password: Password


class UserUpdate(BaseModel):
    first_name: Name | None = None
    last_name: Name | None = None
    email: Email | None = None
    password: Password | None = None
    bio: str | None = Field(default=None, max_length=2000)
    avatar_url: Url | None = None


class UserRead(UserSummary):
    role: Role
    bio: str | None
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Durée de validité en secondes")
