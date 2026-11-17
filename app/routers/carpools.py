from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import (
    CurrentUser,
    can_view_event,
    conflict,
    forbidden,
    is_admin,
    not_found,
    reject_nulls,
    require_event_member,
    viewable_event,
)

router = APIRouter(tags=["Covoiturage (bonus)"])


def _offer(db: Session, offer_id: int, user: models.User) -> models.CarpoolOffer:
    offer = db.get(models.CarpoolOffer, offer_id)
    if offer is None or not can_view_event(offer.event, user):
        raise not_found("Covoiturage")
    return offer


def _is_driver_or_organizer(offer: models.CarpoolOffer, user: models.User) -> bool:
    return offer.driver_id == user.id or offer.event.is_organizer(user.id) or is_admin(user)


@router.post(
    "/events/{event_id}/carpools", response_model=schemas.CarpoolRead, status_code=status.HTTP_201_CREATED
)
def create_offer(event_id: int, payload: schemas.CarpoolCreate, current: CurrentUser, db: Session = Depends(get_db)):
    """Propose un trajet dont l'utilisateur connecté est le conducteur (lieu et heure de départ, prix,
    places, temps maximum d'écart). Le covoiturage doit être activé et le conducteur doit participer."""
    event = viewable_event(db, event_id, current)
    if not event.carpool_enabled:
        raise conflict("Le covoiturage n'est pas activé pour cet événement")
    require_event_member(event, current, "proposer un covoiturage")
    offer = models.CarpoolOffer(event=event, driver_id=current.id, **payload.model_dump())
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer


@router.get("/events/{event_id}/carpools", response_model=list[schemas.CarpoolRead])
def list_offers(event_id: int, current: CurrentUser, available_only: bool = False, db: Session = Depends(get_db)):
    """Trajets proposés pour un événement (`available_only=true` : seulement ceux avec des places libres)."""
    offers = viewable_event(db, event_id, current).carpools
    return [o for o in offers if o.remaining_seats > 0] if available_only else offers


@router.get("/carpools/{offer_id}", response_model=schemas.CarpoolRead)
def get_offer(offer_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Détail d'un trajet et de ses passagers."""
    return _offer(db, offer_id, current)


@router.patch("/carpools/{offer_id}", response_model=schemas.CarpoolRead)
def update_offer(offer_id: int, payload: schemas.CarpoolUpdate, current: CurrentUser, db: Session = Depends(get_db)):
    """Modifie un trajet (conducteur uniquement). Le nombre de places ne peut pas descendre sous le
    nombre de passagers."""
    offer = _offer(db, offer_id, current)
    if offer.driver_id != current.id and not is_admin(current):
        raise forbidden("Seul le conducteur peut modifier ce trajet")
    data = payload.model_dump(exclude_unset=True)
    reject_nulls(data, tuple(data))
    if "seats" in data and data["seats"] < len(offer.bookings):
        raise conflict(f"{len(offer.bookings)} passagers sont déjà inscrits")
    for field, value in data.items():
        setattr(offer, field, value)
    db.commit()
    db.refresh(offer)
    return offer


@router.delete("/carpools/{offer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_offer(offer_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime un trajet et ses réservations (conducteur ou organisateur)."""
    offer = _offer(db, offer_id, current)
    if not _is_driver_or_organizer(offer, current):
        raise forbidden("Seul le conducteur ou un organisateur peut supprimer ce trajet")
    db.delete(offer)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/carpools/{offer_id}/bookings", response_model=schemas.CarpoolRead, status_code=status.HTTP_201_CREATED)
def book_seat(offer_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Réserve une place pour l'utilisateur connecté, qui doit participer à l'événement ; 409 si le
    trajet est complet, s'il est déjà inscrit ou s'il est le conducteur."""
    offer = _offer(db, offer_id, current)
    require_event_member(offer.event, current, "réserver un covoiturage")
    if current.id == offer.driver_id:
        raise conflict("Le conducteur ne peut pas réserver son propre trajet")
    if any(b.passenger_id == current.id for b in offer.bookings):
        raise conflict("Vous avez déjà réservé ce trajet")
    if offer.remaining_seats <= 0:
        raise conflict("Ce trajet est complet")
    offer.bookings.append(models.CarpoolBooking(passenger_id=current.id))
    db.commit()
    db.refresh(offer)
    return offer


@router.delete("/carpools/{offer_id}/bookings/{passenger_id}", response_model=schemas.CarpoolRead)
def cancel_booking(offer_id: int, passenger_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Annule une réservation (le passager lui-même, le conducteur ou un organisateur)."""
    offer = _offer(db, offer_id, current)
    if passenger_id != current.id and not _is_driver_or_organizer(offer, current):
        raise forbidden("Seul le passager, le conducteur ou un organisateur peut annuler cette réservation")
    booking = next((b for b in offer.bookings if b.passenger_id == passenger_id), None)
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Réservation introuvable")
    offer.bookings.remove(booking)
    db.commit()
    db.refresh(offer)
    return offer
