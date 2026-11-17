from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import (
    CurrentUser,
    conflict,
    escape_like,
    forbidden,
    get_or_404,
    is_admin,
    load_users,
    reject_nulls,
    require_event_organizer,
    require_self_or,
    unprocessable,
    viewable_event,
)

router = APIRouter(prefix="/events", tags=["Événements"])


def _check_group_organizers(group: models.Group, organizers: list[models.User]) -> None:
    for user in organizers:
        if not group.is_member(user.id):
            raise forbidden("Les organisateurs d'un événement de groupe doivent être membres du groupe")
        if not group.allow_member_events and not group.is_admin(user.id):
            raise forbidden("Ce groupe n'autorise que ses administrateurs à organiser des événements")


@router.post("", response_model=schemas.EventRead, status_code=status.HTTP_201_CREATED)
def create_event(payload: schemas.EventCreate, current: CurrentUser, db: Session = Depends(get_db)):
    """Étape 1 : configuration de l'événement (nom, description, dates, lieu, photo de couverture,
    visibilité, organisateurs et participants). L'utilisateur connecté en est organisateur d'office.

    Si `group_id` est fourni, les organisateurs doivent être membres du groupe (administrateurs si le
    groupe interdit aux membres de créer des événements) et, avec `invite_group_members=true`, tous
    les membres du groupe sont invités en un clic."""
    data = payload.model_dump(exclude={"organizer_ids", "participant_ids", "invite_group_members"})
    event = models.Event(**data)
    organizers = load_users(db, [current.id, *payload.organizer_ids])
    participants = load_users(db, payload.participant_ids)

    if payload.group_id is not None:
        group = get_or_404(db, models.Group, payload.group_id, "Groupe")
        _check_group_organizers(group, organizers)
        if payload.invite_group_members:
            participants += [m for m in group.members if m not in participants]

    event.organizers = organizers
    event.participants = [p for p in participants if p not in organizers]
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("", response_model=list[schemas.EventRead])
def list_events(
    current: CurrentUser,
    q: str | None = Query(None, max_length=100, description="Recherche dans le nom, la description ou le lieu"),
    visibility: models.Visibility | None = None,
    location: str | None = Query(None, max_length=100),
    starts_after: datetime | None = None,
    starts_before: datetime | None = None,
    organizer_id: int | None = None,
    participant_id: int | None = None,
    group_id: int | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Recherche d'événements : événements publics et événements privés dont l'utilisateur connecté
    est organisateur ou participant."""
    query = select(models.Event)
    if not is_admin(current):
        query = query.where(
            or_(
                models.Event.visibility == models.Visibility.public,
                models.Event.organizers.any(models.User.id == current.id),
                models.Event.participants.any(models.User.id == current.id),
            )
        )
    if q:
        pattern = escape_like(q)
        query = query.where(
            or_(
                models.Event.name.ilike(pattern, escape="\\"),
                models.Event.description.ilike(pattern, escape="\\"),
                models.Event.location.ilike(pattern, escape="\\"),
            )
        )
    if visibility:
        query = query.where(models.Event.visibility == visibility)
    if location:
        query = query.where(models.Event.location.ilike(escape_like(location), escape="\\"))
    if starts_after:
        query = query.where(models.Event.start_date >= starts_after.replace(tzinfo=None))
    if starts_before:
        query = query.where(models.Event.start_date <= starts_before.replace(tzinfo=None))
    if organizer_id is not None:
        query = query.where(models.Event.organizers.any(models.User.id == organizer_id))
    if participant_id is not None:
        query = query.where(models.Event.participants.any(models.User.id == participant_id))
    if group_id is not None:
        query = query.where(models.Event.group_id == group_id)
    query = query.order_by(models.Event.start_date).offset(skip).limit(limit)
    return db.scalars(query).all()


@router.get("/{event_id}", response_model=schemas.EventRead)
def get_event(event_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Détail d'un événement. Un événement privé n'est visible que par ses invités (404 sinon)."""
    return viewable_event(db, event_id, current)


@router.patch("/{event_id}", response_model=schemas.EventRead)
def update_event(event_id: int, payload: schemas.EventUpdate, current: CurrentUser, db: Session = Depends(get_db)):
    """Modifie partiellement un événement (organisateurs uniquement). La date de fin doit rester
    postérieure à la date de début et la billetterie n'est possible que sur un événement public."""
    event = viewable_event(db, event_id, current)
    require_event_organizer(event, current, "modifier l'événement")
    data = payload.model_dump(exclude_unset=True)
    reject_nulls(data, (
        "name", "description", "start_date", "end_date", "location", "visibility", "organizer_ids",
        "participant_ids", "ticketing_enabled", "shopping_list_enabled", "carpool_enabled",
    ))

    if data.get("end_date", event.end_date) <= data.get("start_date", event.start_date):
        raise unprocessable("La date de fin doit être postérieure à la date de début")
    visibility = data.get("visibility", event.visibility)
    if data.get("ticketing_enabled", event.ticketing_enabled) and visibility != models.Visibility.public:
        raise unprocessable("La billetterie n'est disponible que pour les événements publics")

    organizer_ids = data.pop("organizer_ids", None)
    participant_ids = data.pop("participant_ids", None)
    if organizer_ids is not None:
        organizers = load_users(db, organizer_ids)
        if event.group is not None:
            _check_group_organizers(event.group, organizers)
        event.organizers = organizers
    if participant_ids is not None:
        event.participants = load_users(db, participant_ids)
    for field, value in data.items():
        setattr(event, field, value)

    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(event_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime un événement et tout ce qui lui est rattaché (organisateurs uniquement)."""
    event = viewable_event(db, event_id, current)
    require_event_organizer(event, current, "supprimer l'événement")
    db.delete(event)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{event_id}/organizers/{user_id}", response_model=schemas.EventRead)
def add_organizer(event_id: int, user_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Ajoute un organisateur (organisateurs uniquement). Il est retiré des participants s'il en faisait partie."""
    event = viewable_event(db, event_id, current)
    require_event_organizer(event, current, "gérer les organisateurs")
    user = load_users(db, [user_id])[0]
    if event.group is not None:
        _check_group_organizers(event.group, [user])
    if user not in event.organizers:
        event.organizers.append(user)
        if user in event.participants:
            event.participants.remove(user)
        db.commit()
        db.refresh(event)
    return event


@router.delete("/{event_id}/organizers/{user_id}", response_model=schemas.EventRead)
def remove_organizer(event_id: int, user_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Retire un organisateur (organisateurs uniquement). Un événement doit en garder au moins un (409)."""
    event = viewable_event(db, event_id, current)
    require_event_organizer(event, current, "gérer les organisateurs")
    user = load_users(db, [user_id])[0]
    if user not in event.organizers:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cet utilisateur n'est pas organisateur")
    if len(event.organizers) == 1:
        raise conflict("Un événement doit avoir au moins un organisateur")
    event.organizers.remove(user)
    db.commit()
    db.refresh(event)
    return event


@router.post("/{event_id}/participants/{user_id}", response_model=schemas.EventRead)
def add_participant(event_id: int, user_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Ajoute un participant. Un organisateur peut inviter n'importe qui ; un utilisateur peut
    s'inscrire lui-même à un événement public."""
    event = viewable_event(db, event_id, current)
    self_join = user_id == current.id and event.visibility == models.Visibility.public
    if not self_join:
        require_event_organizer(event, current, "inviter des participants")
    user = load_users(db, [user_id])[0]
    if not event.is_member(user.id):
        event.participants.append(user)
        db.commit()
        db.refresh(event)
    return event


@router.delete("/{event_id}/participants/{user_id}", response_model=schemas.EventRead)
def remove_participant(event_id: int, user_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Retire un participant (organisateurs, ou le participant lui-même)."""
    event = viewable_event(db, event_id, current)
    require_self_or(event.is_organizer(current.id), user_id, current,
                    "Seuls les organisateurs ou le participant lui-même peuvent le retirer")
    user = load_users(db, [user_id])[0]
    if user not in event.participants:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cet utilisateur n'est pas participant")
    event.participants.remove(user)
    db.commit()
    db.refresh(event)
    return event


@router.post("/{event_id}/invite-group-members", response_model=schemas.EventRead)
def invite_group_members(event_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Invite en un clic tous les membres du groupe de l'événement (organisateurs uniquement)."""
    event = viewable_event(db, event_id, current)
    require_event_organizer(event, current, "inviter des participants")
    if event.group is None:
        raise conflict("Cet événement n'est rattaché à aucun groupe")
    for member in event.group.members:
        if not event.is_member(member.id):
            event.participants.append(member)
    db.commit()
    db.refresh(event)
    return event


@router.get("/{event_id}/stats", response_model=schemas.EventStats)
def event_stats(event_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Tableau de bord d'un événement (organisateurs uniquement) : participants, activité, billetterie,
    shopping list, covoiturage."""
    event = viewable_event(db, event_id, current)
    require_event_organizer(event, current, "consulter les statistiques")
    return schemas.EventStats(
        event_id=event.id,
        organizers_count=len(event.organizers),
        participants_count=len(event.participants),
        messages_count=len(event.thread.messages) if event.thread else 0,
        albums_count=len(event.albums),
        photos_count=sum(a.photo_count for a in event.albums),
        polls_count=len(event.polls),
        tickets_sold=sum(t.sold for t in event.ticket_types),
        tickets_available=sum(t.remaining for t in event.ticket_types),
        ticket_revenue=round(sum(t.price * t.sold for t in event.ticket_types), 2),
        shopping_items_count=len(event.shopping_items),
        carpool_offers_count=len(event.carpools),
        carpool_seats_remaining=sum(c.remaining_seats for c in event.carpools),
    )


@router.get("/{event_id}/share", response_model=schemas.ShareLinks)
def share_event(event_id: int, request: Request, current: CurrentUser, db: Session = Depends(get_db)):
    """Liens de partage sur les autres réseaux sociaux. Réservé aux événements publics ;
    un événement de groupe ne peut être partagé que si le groupe est public."""
    event = viewable_event(db, event_id, current)
    if event.visibility != models.Visibility.public:
        raise forbidden("Un événement privé ne peut pas être partagé")
    if event.group is not None and event.group.type != models.GroupType.public:
        raise forbidden("Seuls les événements des groupes publics peuvent être partagés")
    url = str(request.url_for("get_event", event_id=event.id))
    u, text = quote(url, safe=""), quote(event.name, safe="")
    return schemas.ShareLinks(
        event_id=event.id,
        url=url,
        links={
            "facebook": f"https://www.facebook.com/sharer/sharer.php?u={u}",
            "x": f"https://twitter.com/intent/tweet?url={u}&text={text}",
            "linkedin": f"https://www.linkedin.com/sharing/share-offsite/?url={u}",
            "whatsapp": f"https://wa.me/?text={text}%20{u}",
            "email": f"mailto:?subject={text}&body={u}",
        },
    )
