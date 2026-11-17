from enum import Enum

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import (
    CurrentUser,
    can_view_event,
    can_view_group,
    conflict,
    escape_like,
    forbidden,
    get_or_404,
    is_admin,
    reject_nulls,
)
from ..security import hash_password

router = APIRouter(prefix="/users", tags=["Utilisateurs"])


class EventRole(str, Enum):
    all = "all"
    organizer = "organizer"
    participant = "participant"


def _ensure_email_free(db: Session, email: str, exclude_id: int | None = None) -> None:
    query = select(models.User.id).where(models.User.email == email)
    if exclude_id is not None:
        query = query.where(models.User.id != exclude_id)
    if db.scalar(query) is not None:
        raise conflict("Un utilisateur avec cet email existe déjà")


def _require_self_or_admin(user_id: int, user: models.User) -> None:
    if user.id != user_id and not is_admin(user):
        raise forbidden("Vous ne pouvez modifier que votre propre compte")


@router.post("", response_model=schemas.UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    """Inscription (route publique). L'email est unique (insensible à la casse) : 409 s'il est déjà
    utilisé. Le mot de passe doit contenir 8 caractères minimum dont une majuscule, une minuscule et
    un chiffre ; il est haché avec bcrypt et n'est jamais renvoyé. Le rôle est toujours `user`."""
    _ensure_email_free(db, payload.email)
    user = models.User(
        **payload.model_dump(exclude={"password"}),
        password_hash=hash_password(payload.password),
        role=models.Role.user,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("", response_model=list[schemas.UserRead])
def list_users(
    current: CurrentUser,
    q: str | None = Query(None, max_length=100, description="Recherche sur prénom, nom ou email"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Liste les utilisateurs, avec recherche optionnelle et pagination."""
    query = select(models.User)
    if q:
        pattern = escape_like(q)
        query = query.where(
            or_(
                models.User.first_name.ilike(pattern, escape="\\"),
                models.User.last_name.ilike(pattern, escape="\\"),
                models.User.email.ilike(pattern, escape="\\"),
            )
        )
    return db.scalars(query.order_by(models.User.id).offset(skip).limit(limit)).all()


@router.get("/{user_id}", response_model=schemas.UserRead)
def get_user(user_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Détail d'un utilisateur."""
    return get_or_404(db, models.User, user_id, "Utilisateur")


@router.patch("/{user_id}", response_model=schemas.UserRead)
def update_user(user_id: int, payload: schemas.UserUpdate, current: CurrentUser, db: Session = Depends(get_db)):
    """Modifie partiellement un utilisateur. Réservé à l'utilisateur lui-même ou à un administrateur."""
    _require_self_or_admin(user_id, current)
    user = get_or_404(db, models.User, user_id, "Utilisateur")
    data = payload.model_dump(exclude_unset=True)
    reject_nulls(data, ("first_name", "last_name", "email", "password"))
    if "email" in data:
        _ensure_email_free(db, data["email"], exclude_id=user_id)
    if "password" in data:
        user.password_hash = hash_password(data.pop("password"))
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime un compte. Réservé à l'utilisateur lui-même ou à un administrateur. Refusé (409) s'il
    est le seul organisateur d'un événement ou le seul administrateur d'un groupe."""
    _require_self_or_admin(user_id, current)
    user = get_or_404(db, models.User, user_id, "Utilisateur")
    blocking = [f"l'événement « {e.name} »" for e in user.organized_events if len(e.organizers) == 1]
    blocking += [f"le groupe « {g.name} »" for g in user.administered_groups if len(g.admins) == 1]
    if blocking:
        raise conflict("Impossible de supprimer : seul responsable de " + ", ".join(blocking))
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{user_id}/events", response_model=list[schemas.EventSummary])
def list_user_events(
    user_id: int,
    current: CurrentUser,
    role: EventRole = Query(EventRole.all, description="all, organizer ou participant"),
    db: Session = Depends(get_db),
):
    """Événements auxquels l'utilisateur est lié, triés par date. Les événements privés n'apparaissent
    que si l'utilisateur connecté y a lui-même accès."""
    user = get_or_404(db, models.User, user_id, "Utilisateur")
    events: dict[int, models.Event] = {}
    if role in (EventRole.all, EventRole.organizer):
        events.update({e.id: e for e in user.organized_events})
    if role in (EventRole.all, EventRole.participant):
        events.update({e.id: e for e in user.participating_events})
    visible = [e for e in events.values() if can_view_event(e, current)]
    return sorted(visible, key=lambda e: e.start_date)


@router.get("/{user_id}/groups", response_model=list[schemas.GroupSummary])
def list_user_groups(user_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Groupes dont l'utilisateur est membre (les groupes secrets ne sont visibles que de leurs membres)."""
    user = get_or_404(db, models.User, user_id, "Utilisateur")
    return sorted((g for g in user.groups if can_view_group(g, current)), key=lambda g: g.id)
