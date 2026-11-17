from typing import Annotated, TypeVar

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .security import decode_access_token

T = TypeVar("T")

bearer_scheme = HTTPBearer(auto_error=False, description="JWT obtenu via POST /auth/login")


def get_or_404(db: Session, model: type[T], obj_id: int, label: str) -> T:
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} introuvable")
    return obj


def load_users(db: Session, ids: list[int]) -> list[models.User]:
    unique_ids = list(dict.fromkeys(ids))
    if not unique_ids:
        return []
    users = db.scalars(select(models.User).where(models.User.id.in_(unique_ids))).all()
    missing = set(unique_ids) - {u.id for u in users}
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Utilisateur(s) introuvable(s) : {sorted(missing)}"
        )
    by_id = {u.id: u for u in users}
    return [by_id[i] for i in unique_ids]


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def forbidden(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail)


def conflict(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail)


def unprocessable(detail: str) -> HTTPException:
    return HTTPException(422, detail)


def not_found(label: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{label} introuvable")


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Session = Depends(get_db),
) -> models.User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized('Jeton manquant : en-tête attendu "Authorization: Bearer <token>"')
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise unauthorized("Jeton expiré")
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise unauthorized("Jeton invalide")
    user = db.get(models.User, user_id)
    if user is None:
        raise unauthorized("Jeton invalide")
    return user


CurrentUser = Annotated[models.User, Depends(get_current_user)]


def is_admin(user: models.User) -> bool:
    return user.role == models.Role.admin


def escape_like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def can_view_event(event: models.Event, user: models.User) -> bool:
    return event.visibility == models.Visibility.public or event.is_member(user.id) or is_admin(user)


def viewable_event(db: Session, event_id: int, user: models.User) -> models.Event:
    event = db.get(models.Event, event_id)
    if event is None or not can_view_event(event, user):
        raise not_found("Événement")
    return event


def require_event_member(event: models.Event, user: models.User, action: str) -> None:
    if not event.is_member(user.id):
        raise forbidden(f"Seuls les participants ou organisateurs de l'événement peuvent {action}")


def require_event_organizer(event: models.Event, user: models.User, action: str) -> None:
    if not (event.is_organizer(user.id) or is_admin(user)):
        raise forbidden(f"Seuls les organisateurs de l'événement peuvent {action}")


def can_view_group(group: models.Group, user: models.User) -> bool:
    return group.type != models.GroupType.secret or group.is_member(user.id) or is_admin(user)


def can_read_group_content(group: models.Group, user: models.User) -> bool:
    return group.type == models.GroupType.public or group.is_member(user.id) or is_admin(user)


def viewable_group(db: Session, group_id: int, user: models.User) -> models.Group:
    group = db.get(models.Group, group_id)
    if group is None or not can_view_group(group, user):
        raise not_found("Groupe")
    return group


def require_group_admin(group: models.Group, user: models.User, action: str) -> None:
    if not (group.is_admin(user.id) or is_admin(user)):
        raise forbidden(f"Seuls les administrateurs du groupe peuvent {action}")


def require_self_or(condition: bool, user_id: int, user: models.User, detail: str) -> None:
    if not (user.id == user_id or condition or is_admin(user)):
        raise forbidden(detail)


def reject_nulls(data: dict, fields: tuple[str, ...]) -> None:
    for field in fields:
        if field in data and data[field] is None:
            raise unprocessable(f"'{field}' ne peut pas être null")
