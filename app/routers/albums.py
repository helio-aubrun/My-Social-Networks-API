from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import (
    CurrentUser,
    can_view_event,
    forbidden,
    not_found,
    reject_nulls,
    require_event_member,
    require_event_organizer,
    viewable_event,
)

router = APIRouter(tags=["Albums photo"])


def _album(db: Session, album_id: int, user: models.User) -> models.Album:
    album = db.get(models.Album, album_id)
    if album is None or not can_view_event(album.event, user):
        raise not_found("Album")
    return album


def _photo(db: Session, photo_id: int, user: models.User) -> models.Photo:
    photo = db.get(models.Photo, photo_id)
    if photo is None or not can_view_event(photo.album.event, user):
        raise not_found("Photo")
    return photo


def _photo_comment(db: Session, comment_id: int, user: models.User) -> models.PhotoComment:
    comment = db.get(models.PhotoComment, comment_id)
    if comment is None or not can_view_event(comment.photo.album.event, user):
        raise not_found("Commentaire")
    return comment


def _require_author_or_organizer(author_id: int, event: models.Event, user: models.User) -> None:
    if author_id != user.id:
        require_event_organizer(event, user, "supprimer le contenu des autres")


@router.post("/events/{event_id}/albums", response_model=schemas.AlbumRead, status_code=status.HTTP_201_CREATED)
def create_album(event_id: int, payload: schemas.AlbumCreate, current: CurrentUser, db: Session = Depends(get_db)):
    """Crée un album photo associé à un événement (organisateurs uniquement)."""
    event = viewable_event(db, event_id, current)
    require_event_organizer(event, current, "créer un album")
    album = models.Album(event=event, **payload.model_dump())
    db.add(album)
    db.commit()
    db.refresh(album)
    return album


@router.get("/events/{event_id}/albums", response_model=list[schemas.AlbumRead])
def list_albums(event_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Albums d'un événement, avec leur nombre de photos."""
    return viewable_event(db, event_id, current).albums


@router.get("/albums/{album_id}", response_model=schemas.AlbumRead)
def get_album(album_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Détail d'un album."""
    return _album(db, album_id, current)


@router.patch("/albums/{album_id}", response_model=schemas.AlbumRead)
def update_album(album_id: int, payload: schemas.AlbumUpdate, current: CurrentUser, db: Session = Depends(get_db)):
    """Renomme un album ou modifie sa description (organisateurs uniquement)."""
    album = _album(db, album_id, current)
    require_event_organizer(album.event, current, "modifier un album")
    data = payload.model_dump(exclude_unset=True)
    reject_nulls(data, ("name",))
    for field, value in data.items():
        setattr(album, field, value)
    db.commit()
    db.refresh(album)
    return album


@router.delete("/albums/{album_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_album(album_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime un album, ses photos et leurs commentaires (organisateurs uniquement)."""
    album = _album(db, album_id, current)
    require_event_organizer(album.event, current, "supprimer un album")
    db.delete(album)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/albums/{album_id}/photos", response_model=schemas.PhotoRead, status_code=status.HTTP_201_CREATED)
def create_photo(album_id: int, payload: schemas.PhotoCreate, current: CurrentUser, db: Session = Depends(get_db)):
    """Poste une photo (URL http(s)) au nom de l'utilisateur connecté, qui doit être participant
    (ou organisateur) de l'événement."""
    album = _album(db, album_id, current)
    require_event_member(album.event, current, "poster des photos")
    photo = models.Photo(album=album, author_id=current.id, **payload.model_dump())
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


@router.get("/albums/{album_id}/photos", response_model=list[schemas.PhotoRead])
def list_photos(album_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Photos d'un album avec leurs commentaires."""
    return _album(db, album_id, current).photos


@router.get("/photos/{photo_id}", response_model=schemas.PhotoRead)
def get_photo(photo_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Détail d'une photo et de ses commentaires."""
    return _photo(db, photo_id, current)


@router.patch("/photos/{photo_id}", response_model=schemas.PhotoRead)
def update_photo(photo_id: int, payload: schemas.PhotoUpdate, current: CurrentUser, db: Session = Depends(get_db)):
    """Modifie l'URL ou la légende d'une photo (auteur uniquement)."""
    photo = _photo(db, photo_id, current)
    if photo.author_id != current.id:
        raise forbidden("Seul l'auteur peut modifier cette photo")
    data = payload.model_dump(exclude_unset=True)
    reject_nulls(data, ("url",))
    for field, value in data.items():
        setattr(photo, field, value)
    db.commit()
    db.refresh(photo)
    return photo


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(photo_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime une photo et ses commentaires (auteur ou organisateur)."""
    photo = _photo(db, photo_id, current)
    _require_author_or_organizer(photo.author_id, photo.album.event, current)
    db.delete(photo)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/photos/{photo_id}/comments", response_model=schemas.CommentRead, status_code=status.HTTP_201_CREATED
)
def create_photo_comment(photo_id: int, payload: schemas.CommentCreate, current: CurrentUser, db: Session = Depends(get_db)):
    """Commente une photo. Réservé aux participants (et organisateurs) de l'événement."""
    photo = _photo(db, photo_id, current)
    require_event_member(photo.album.event, current, "commenter les photos")
    comment = models.PhotoComment(photo=photo, author_id=current.id, content=payload.content)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/photos/{photo_id}/comments", response_model=list[schemas.CommentRead])
def list_photo_comments(photo_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Commentaires d'une photo."""
    return _photo(db, photo_id, current).comments


@router.patch("/photo-comments/{comment_id}", response_model=schemas.CommentRead)
def update_photo_comment(
    comment_id: int, payload: schemas.CommentUpdate, current: CurrentUser, db: Session = Depends(get_db)
):
    """Modifie un commentaire de photo (auteur uniquement)."""
    comment = _photo_comment(db, comment_id, current)
    if comment.author_id != current.id:
        raise forbidden("Seul l'auteur peut modifier ce commentaire")
    comment.content = payload.content
    db.commit()
    db.refresh(comment)
    return comment


@router.delete("/photo-comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo_comment(comment_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime un commentaire de photo (auteur ou organisateur)."""
    comment = _photo_comment(db, comment_id, current)
    _require_author_or_organizer(comment.author_id, comment.photo.album.event, current)
    db.delete(comment)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
