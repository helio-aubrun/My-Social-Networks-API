from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import (
    CurrentUser,
    can_view_event,
    conflict,
    get_or_404,
    not_found,
    reject_nulls,
    require_event_organizer,
    unprocessable,
    viewable_event,
)

router = APIRouter(tags=["Billetterie"])


def _ticket_type(db: Session, ticket_type_id: int, user: models.User) -> models.TicketType:
    ticket_type = db.get(models.TicketType, ticket_type_id)
    if ticket_type is None or not can_view_event(ticket_type.event, user):
        raise not_found("Type de billet")
    return ticket_type


def _ticket_for_organizer(db: Session, ticket_id: int, user: models.User) -> models.Ticket:
    ticket = db.get(models.Ticket, ticket_id)
    if ticket is None or not can_view_event(ticket.ticket_type.event, user):
        raise not_found("Billet")
    require_event_organizer(ticket.ticket_type.event, user, "gérer les billets")
    return ticket


@router.post(
    "/events/{event_id}/ticket-types", response_model=schemas.TicketTypeRead, status_code=status.HTTP_201_CREATED
)
def create_ticket_type(
    event_id: int, payload: schemas.TicketTypeCreate, current: CurrentUser, db: Session = Depends(get_db)
):
    """Crée un type de billet (nom, montant, quantité limitée), par un organisateur. L'événement doit
    être public et avoir la billetterie activée."""
    event = viewable_event(db, event_id, current)
    require_event_organizer(event, current, "gérer la billetterie")
    if not event.ticketing_enabled:
        raise conflict("La billetterie n'est pas activée pour cet événement")
    ticket_type = models.TicketType(event=event, **payload.model_dump())
    db.add(ticket_type)
    db.commit()
    db.refresh(ticket_type)
    return ticket_type


@router.get("/events/{event_id}/ticket-types", response_model=list[schemas.TicketTypeRead])
def list_ticket_types(event_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Types de billets d'un événement avec billets vendus et restants."""
    return viewable_event(db, event_id, current).ticket_types


@router.get("/ticket-types/{ticket_type_id}", response_model=schemas.TicketTypeRead)
def get_ticket_type(ticket_type_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Détail d'un type de billet."""
    return _ticket_type(db, ticket_type_id, current)


@router.patch("/ticket-types/{ticket_type_id}", response_model=schemas.TicketTypeRead)
def update_ticket_type(
    ticket_type_id: int, payload: schemas.TicketTypeUpdate, current: CurrentUser, db: Session = Depends(get_db)
):
    """Modifie un type de billet (organisateurs). La quantité ne peut pas descendre sous les billets vendus."""
    ticket_type = _ticket_type(db, ticket_type_id, current)
    require_event_organizer(ticket_type.event, current, "gérer la billetterie")
    data = payload.model_dump(exclude_unset=True)
    reject_nulls(data, ("name", "price", "quantity"))
    if "quantity" in data and data["quantity"] < ticket_type.sold:
        raise conflict(f"{ticket_type.sold} billets ont déjà été vendus pour ce type")
    for field, value in data.items():
        setattr(ticket_type, field, value)
    db.commit()
    db.refresh(ticket_type)
    return ticket_type


@router.delete("/ticket-types/{ticket_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ticket_type(ticket_type_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime un type de billet (organisateurs). Refusé (409) si des billets ont déjà été vendus."""
    ticket_type = _ticket_type(db, ticket_type_id, current)
    require_event_organizer(ticket_type.event, current, "gérer la billetterie")
    if ticket_type.sold:
        raise conflict("Impossible de supprimer un type de billet déjà vendu")
    db.delete(ticket_type)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/ticket-types/{ticket_type_id}/tickets", response_model=schemas.TicketRead, status_code=status.HTTP_201_CREATED
)
def buy_ticket(ticket_type_id: int, payload: schemas.TicketPurchase, db: Session = Depends(get_db)):
    """Achète un billet. Route publique : l'acheteur est une personne extérieure sans compte (nom,
    prénom, email, adresse complète ; date d'achat automatique). Une personne (email) ne peut obtenir
    qu'un seul billet par événement (409) et un type épuisé renvoie 409."""
    ticket_type = get_or_404(db, models.TicketType, ticket_type_id, "Type de billet")
    event = ticket_type.event
    if not event.ticketing_enabled or event.visibility != models.Visibility.public:
        raise conflict("La billetterie n'est pas ouverte pour cet événement")
    if ticket_type.remaining <= 0:
        raise conflict("Ce type de billet est épuisé")
    existing = db.scalar(
        select(models.Ticket.id).where(models.Ticket.event_id == event.id, models.Ticket.email == payload.email)
    )
    if existing is not None:
        raise conflict("Cette personne possède déjà un billet pour cet événement")
    ticket = models.Ticket(ticket_type=ticket_type, event_id=event.id, **payload.model_dump())
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("/events/{event_id}/tickets", response_model=list[schemas.TicketRead])
def list_tickets(
    event_id: int,
    current: CurrentUser,
    ticket_type_id: int | None = None,
    email: str | None = Query(None, max_length=255, description="Retrouver le billet d'une personne"),
    db: Session = Depends(get_db),
):
    """Billets vendus (données personnelles des acheteurs : organisateurs uniquement)."""
    event = viewable_event(db, event_id, current)
    require_event_organizer(event, current, "consulter les billets vendus")
    query = select(models.Ticket).where(models.Ticket.event_id == event_id)
    if ticket_type_id is not None:
        query = query.where(models.Ticket.ticket_type_id == ticket_type_id)
    if email:
        query = query.where(models.Ticket.email == email.strip().lower())
    return db.scalars(query.order_by(models.Ticket.id)).all()


@router.get("/tickets/{ticket_id}", response_model=schemas.TicketRead)
def get_ticket(ticket_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Détail d'un billet (organisateurs uniquement)."""
    return _ticket_for_organizer(db, ticket_id, current)


@router.patch("/tickets/{ticket_id}", response_model=schemas.TicketRead)
def update_ticket(ticket_id: int, payload: schemas.TicketUpdate, current: CurrentUser, db: Session = Depends(get_db)):
    """Corrige les informations de l'acheteur (organisateurs uniquement)."""
    ticket = _ticket_for_organizer(db, ticket_id, current)
    data = payload.model_dump(exclude_unset=True)
    if any(v is None for v in data.values()):
        raise unprocessable("Les informations de l'acheteur ne peuvent pas être null")
    for field, value in data.items():
        setattr(ticket, field, value)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.delete("/tickets/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ticket(ticket_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Annule un billet (organisateurs uniquement) : la place redevient disponible."""
    ticket = _ticket_for_organizer(db, ticket_id, current)
    db.delete(ticket)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
