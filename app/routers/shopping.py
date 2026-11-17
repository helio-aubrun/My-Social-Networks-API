from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import (
    CurrentUser,
    can_view_event,
    conflict,
    not_found,
    reject_nulls,
    require_event_member,
    require_event_organizer,
    viewable_event,
)

router = APIRouter(tags=["Shopping list"])


def _key(name: str) -> str:
    return " ".join(name.lower().split())


def _item(db: Session, item_id: int, user: models.User) -> models.ShoppingItem:
    item = db.get(models.ShoppingItem, item_id)
    if item is None or not can_view_event(item.event, user):
        raise not_found("Article")
    return item


def _require_owner_or_organizer(item: models.ShoppingItem, user: models.User) -> None:
    if item.user_id != user.id:
        require_event_organizer(item.event, user, "modifier l'article d'un autre participant")


def _ensure_unique(db: Session, event_id: int, name: str, exclude_id: int | None = None) -> None:
    query = select(models.ShoppingItem.id).where(
        models.ShoppingItem.event_id == event_id, models.ShoppingItem.name_key == _key(name)
    )
    if exclude_id is not None:
        query = query.where(models.ShoppingItem.id != exclude_id)
    if db.scalar(query) is not None:
        raise conflict(f"« {name} » est déjà apporté par quelqu'un pour cet événement")


@router.post(
    "/events/{event_id}/shopping-items", response_model=schemas.ShoppingItemRead, status_code=status.HTTP_201_CREATED
)
def create_item(event_id: int, payload: schemas.ShoppingItemCreate, current: CurrentUser, db: Session = Depends(get_db)):
    """Indique ce que l'utilisateur connecté apporte (nom, quantité, heure d'arrivée). Il doit participer
    à l'événement, la shopping list doit être activée et chaque article est unique par événement (409)."""
    event = viewable_event(db, event_id, current)
    if not event.shopping_list_enabled:
        raise conflict("La shopping list n'est pas activée pour cet événement")
    require_event_member(event, current, "compléter la shopping list")
    _ensure_unique(db, event_id, payload.name)
    item = models.ShoppingItem(event=event, user_id=current.id, name_key=_key(payload.name), **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/events/{event_id}/shopping-items", response_model=list[schemas.ShoppingItemRead])
def list_items(event_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Shopping list d'un événement."""
    return viewable_event(db, event_id, current).shopping_items


@router.get("/shopping-items/{item_id}", response_model=schemas.ShoppingItemRead)
def get_item(item_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Détail d'un article."""
    return _item(db, item_id, current)


@router.patch("/shopping-items/{item_id}", response_model=schemas.ShoppingItemRead)
def update_item(item_id: int, payload: schemas.ShoppingItemUpdate, current: CurrentUser, db: Session = Depends(get_db)):
    """Modifie un article (celui qui l'apporte ou un organisateur). Le nom doit rester unique."""
    item = _item(db, item_id, current)
    _require_owner_or_organizer(item, current)
    data = payload.model_dump(exclude_unset=True)
    reject_nulls(data, ("name", "quantity", "arrival_time"))
    if "name" in data:
        _ensure_unique(db, item.event_id, data["name"], exclude_id=item.id)
        item.name_key = _key(data["name"])
    for field, value in data.items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/shopping-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Retire un article (celui qui l'apporte ou un organisateur)."""
    item = _item(db, item_id, current)
    _require_owner_or_organizer(item, current)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
