from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import (
    CurrentUser,
    can_read_group_content,
    can_view_event,
    conflict,
    escape_like,
    forbidden,
    is_admin,
    load_users,
    reject_nulls,
    require_group_admin,
    require_self_or,
    viewable_group,
)

router = APIRouter(prefix="/groups", tags=["Groupes"])


def _merge(admins: list[models.User], members: list[models.User]) -> list[models.User]:
    return admins + [m for m in members if m not in admins]


@router.post("", response_model=schemas.GroupRead, status_code=status.HTTP_201_CREATED)
def create_group(payload: schemas.GroupCreate, current: CurrentUser, db: Session = Depends(get_db)):
    """Crée un groupe (public, privé ou secret). L'utilisateur connecté en est administrateur d'office ;
    les administrateurs sont toujours membres et un fil de discussion est créé pour le groupe."""
    admins = load_users(db, [current.id, *payload.admin_ids])
    members = load_users(db, payload.member_ids)
    group = models.Group(**payload.model_dump(exclude={"admin_ids", "member_ids"}))
    group.admins = admins
    group.members = _merge(admins, members)
    group.thread = models.Thread(title=f"Discussion – {payload.name}")
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.get("", response_model=list[schemas.GroupRead])
def list_groups(
    current: CurrentUser,
    q: str | None = Query(None, max_length=100, description="Recherche sur le nom ou la description"),
    type: models.GroupType | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Liste les groupes. Les groupes secrets n'apparaissent qu'à leurs membres."""
    query = select(models.Group)
    if not is_admin(current):
        query = query.where(
            or_(
                models.Group.type != models.GroupType.secret,
                models.Group.members.any(models.User.id == current.id),
            )
        )
    if q:
        pattern = escape_like(q)
        query = query.where(
            or_(models.Group.name.ilike(pattern, escape="\\"), models.Group.description.ilike(pattern, escape="\\"))
        )
    if type:
        query = query.where(models.Group.type == type)
    return db.scalars(query.order_by(models.Group.id).offset(skip).limit(limit)).all()


@router.get("/{group_id}", response_model=schemas.GroupRead)
def get_group(group_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Détail d'un groupe (404 pour un groupe secret dont on n'est pas membre)."""
    return viewable_group(db, group_id, current)


@router.patch("/{group_id}", response_model=schemas.GroupRead)
def update_group(group_id: int, payload: schemas.GroupUpdate, current: CurrentUser, db: Session = Depends(get_db)):
    """Modifie les paramètres du groupe (administrateurs du groupe uniquement). Les administrateurs
    restent toujours membres."""
    group = viewable_group(db, group_id, current)
    require_group_admin(group, current, "modifier le groupe")
    data = payload.model_dump(exclude_unset=True)
    reject_nulls(data, ("name", "type", "allow_member_posts", "allow_member_events", "admin_ids", "member_ids"))

    admin_ids = data.pop("admin_ids", None)
    member_ids = data.pop("member_ids", None)
    if admin_ids is not None:
        group.admins = load_users(db, admin_ids)
    if member_ids is not None:
        group.members = _merge(group.admins, load_users(db, member_ids))
    elif admin_ids is not None:
        group.members = _merge(group.admins, group.members)
    for field, value in data.items():
        setattr(group, field, value)
    db.commit()
    db.refresh(group)
    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime le groupe et son fil (administrateurs du groupe uniquement). Ses événements sont conservés."""
    group = viewable_group(db, group_id, current)
    require_group_admin(group, current, "supprimer le groupe")
    db.delete(group)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{group_id}/members/{user_id}", response_model=schemas.GroupRead)
def add_member(group_id: int, user_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Ajoute un membre. Un administrateur peut ajouter n'importe qui ; un utilisateur peut rejoindre
    lui-même un groupe public."""
    group = viewable_group(db, group_id, current)
    self_join = user_id == current.id and group.type == models.GroupType.public
    if not self_join:
        require_group_admin(group, current, "ajouter des membres")
    user = load_users(db, [user_id])[0]
    if user not in group.members:
        group.members.append(user)
        db.commit()
        db.refresh(group)
    return group


@router.delete("/{group_id}/members/{user_id}", response_model=schemas.GroupRead)
def remove_member(group_id: int, user_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Retire un membre (administrateurs, ou le membre lui-même). Le dernier administrateur ne peut pas partir (409)."""
    group = viewable_group(db, group_id, current)
    require_self_or(group.is_admin(current.id), user_id, current,
                    "Seuls les administrateurs ou le membre lui-même peuvent le retirer")
    user = load_users(db, [user_id])[0]
    if user not in group.members:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cet utilisateur n'est pas membre du groupe")
    if user in group.admins:
        if len(group.admins) == 1:
            raise conflict("Un groupe doit avoir au moins un administrateur")
        group.admins.remove(user)
    group.members.remove(user)
    db.commit()
    db.refresh(group)
    return group


@router.post("/{group_id}/admins/{user_id}", response_model=schemas.GroupRead)
def add_admin(group_id: int, user_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Nomme un administrateur (administrateurs du groupe uniquement)."""
    group = viewable_group(db, group_id, current)
    require_group_admin(group, current, "nommer des administrateurs")
    user = load_users(db, [user_id])[0]
    if user not in group.admins:
        group.admins.append(user)
    if user not in group.members:
        group.members.append(user)
    db.commit()
    db.refresh(group)
    return group


@router.delete("/{group_id}/admins/{user_id}", response_model=schemas.GroupRead)
def remove_admin(group_id: int, user_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Retire le rôle d'administrateur (l'utilisateur reste membre). Il faut garder au moins un admin."""
    group = viewable_group(db, group_id, current)
    require_group_admin(group, current, "retirer des administrateurs")
    user = load_users(db, [user_id])[0]
    if user not in group.admins:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cet utilisateur n'est pas administrateur")
    if len(group.admins) == 1:
        raise conflict("Un groupe doit avoir au moins un administrateur")
    group.admins.remove(user)
    db.commit()
    db.refresh(group)
    return group


@router.get("/{group_id}/events", response_model=list[schemas.EventSummary])
def list_group_events(group_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Événements du groupe visibles par l'utilisateur connecté, triés par date de début.
    Le contenu d'un groupe privé ou secret est réservé à ses membres."""
    group = viewable_group(db, group_id, current)
    if not can_read_group_content(group, current):
        raise forbidden("Le contenu de ce groupe est réservé à ses membres")
    return sorted((e for e in group.events if can_view_event(e, current)), key=lambda e: e.start_date)
