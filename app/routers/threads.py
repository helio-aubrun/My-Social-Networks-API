from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import (
    CurrentUser,
    can_read_group_content,
    can_view_event,
    conflict,
    forbidden,
    get_or_404,
    is_admin,
    not_found,
    require_event_organizer,
    require_group_admin,
    viewable_event,
    viewable_group,
)

router = APIRouter(tags=["Fils de discussion"])


def _can_read(thread: models.Thread, user: models.User) -> bool:
    if thread.group is not None:
        return can_read_group_content(thread.group, user)
    return can_view_event(thread.event, user)


def _thread(db: Session, thread_id: int, user: models.User) -> models.Thread:
    thread = db.get(models.Thread, thread_id)
    if thread is None or not _can_read(thread, user):
        raise not_found("Fil de discussion")
    return thread


def _message(db: Session, message_id: int, user: models.User) -> models.Message:
    message = db.get(models.Message, message_id)
    if message is None or not _can_read(message.thread, user):
        raise not_found("Message")
    return message


def _comment(db: Session, comment_id: int, user: models.User) -> models.MessageComment:
    comment = db.get(models.MessageComment, comment_id)
    if comment is None or not _can_read(comment.message.thread, user):
        raise not_found("Commentaire")
    return comment


def _is_moderator(thread: models.Thread, user: models.User) -> bool:
    if is_admin(user):
        return True
    if thread.group is not None:
        return thread.group.is_admin(user.id)
    return thread.event.is_organizer(user.id)


def _require_manager(thread: models.Thread, user: models.User) -> None:
    if thread.group is not None:
        require_group_admin(thread.group, user, "gérer ce fil")
    else:
        require_event_organizer(thread.event, user, "gérer ce fil")


def _require_participant(thread: models.Thread, user: models.User) -> None:
    if thread.group is not None:
        if not thread.group.is_member(user.id):
            raise forbidden("Seuls les membres du groupe peuvent intervenir dans ce fil")
    elif not thread.event.is_member(user.id):
        raise forbidden("Seuls les participants et organisateurs de l'événement peuvent intervenir dans ce fil")


def _require_poster(thread: models.Thread, user: models.User) -> None:
    _require_participant(thread, user)
    group = thread.group
    if group is not None and not group.allow_member_posts and not group.is_admin(user.id):
        raise forbidden("Ce groupe n'autorise que ses administrateurs à publier")


def _require_author_or_moderator(author_id: int, thread: models.Thread, user: models.User) -> None:
    if author_id != user.id and not _is_moderator(thread, user):
        raise forbidden("Seul l'auteur ou un modérateur peut supprimer ce contenu")


@router.post("/threads", response_model=schemas.ThreadRead, status_code=status.HTTP_201_CREATED)
def create_thread(payload: schemas.ThreadCreate, current: CurrentUser, db: Session = Depends(get_db)):
    """Crée le fil de discussion d'un groupe OU d'un événement (jamais les deux), par un administrateur
    du groupe ou un organisateur de l'événement. Un seul fil par groupe/événement (409)."""
    if payload.group_id is not None:
        parent = viewable_group(db, payload.group_id, current)
        require_group_admin(parent, current, "créer le fil du groupe")
    else:
        parent = viewable_event(db, payload.event_id, current)
        require_event_organizer(parent, current, "créer le fil de l'événement")
    if parent.thread is not None:
        raise conflict("Un fil de discussion existe déjà pour ce groupe/événement")
    thread = models.Thread(**payload.model_dump())
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


@router.get("/threads", response_model=list[schemas.ThreadRead])
def list_threads(
    current: CurrentUser,
    group_id: int | None = None,
    event_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Liste les fils accessibles à l'utilisateur connecté, filtrables par groupe ou par événement."""
    query = select(models.Thread)
    if group_id is not None:
        query = query.where(models.Thread.group_id == group_id)
    if event_id is not None:
        query = query.where(models.Thread.event_id == event_id)
    return [t for t in db.scalars(query.order_by(models.Thread.id)) if _can_read(t, current)]


@router.get("/threads/{thread_id}", response_model=schemas.ThreadRead)
def get_thread(thread_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Détail d'un fil de discussion."""
    return _thread(db, thread_id, current)


@router.patch("/threads/{thread_id}", response_model=schemas.ThreadRead)
def update_thread(thread_id: int, payload: schemas.ThreadUpdate, current: CurrentUser, db: Session = Depends(get_db)):
    """Renomme un fil (administrateurs du groupe / organisateurs de l'événement)."""
    thread = _thread(db, thread_id, current)
    _require_manager(thread, current)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(thread, field, value)
    db.commit()
    db.refresh(thread)
    return thread


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread(thread_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime un fil, ses messages et commentaires (administrateurs du groupe / organisateurs)."""
    thread = _thread(db, thread_id, current)
    _require_manager(thread, current)
    db.delete(thread)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/threads/{thread_id}/messages", response_model=schemas.MessageRead, status_code=status.HTTP_201_CREATED
)
def create_message(thread_id: int, payload: schemas.MessageCreate, current: CurrentUser, db: Session = Depends(get_db)):
    """Publie un message au nom de l'utilisateur connecté. Il doit être membre du groupe (administrateur
    si le groupe interdit aux membres de publier) ou participant / organisateur de l'événement."""
    thread = _thread(db, thread_id, current)
    _require_poster(thread, current)
    message = models.Message(thread=thread, author_id=current.id, content=payload.content)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


@router.get("/threads/{thread_id}/messages", response_model=list[schemas.MessageRead])
def list_messages(
    thread_id: int,
    current: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Messages du fil (du plus ancien au plus récent) avec leurs commentaires."""
    _thread(db, thread_id, current)
    query = (
        select(models.Message)
        .where(models.Message.thread_id == thread_id)
        .order_by(models.Message.id)
        .offset(skip)
        .limit(limit)
    )
    return db.scalars(query).all()


@router.get("/messages/{message_id}", response_model=schemas.MessageRead)
def get_message(message_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Détail d'un message et de ses commentaires."""
    return _message(db, message_id, current)


@router.patch("/messages/{message_id}", response_model=schemas.MessageRead)
def update_message(message_id: int, payload: schemas.MessageUpdate, current: CurrentUser, db: Session = Depends(get_db)):
    """Modifie le contenu d'un message (auteur uniquement)."""
    message = _message(db, message_id, current)
    if message.author_id != current.id:
        raise forbidden("Seul l'auteur peut modifier ce message")
    message.content = payload.content
    db.commit()
    db.refresh(message)
    return message


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(message_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime un message et ses commentaires (auteur ou modérateur : admin du groupe / organisateur)."""
    message = _message(db, message_id, current)
    _require_author_or_moderator(message.author_id, message.thread, current)
    db.delete(message)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/messages/{message_id}/comments", response_model=schemas.CommentRead, status_code=status.HTTP_201_CREATED
)
def create_message_comment(
    message_id: int, payload: schemas.CommentCreate, current: CurrentUser, db: Session = Depends(get_db)
):
    """Commente un message. Tout membre du groupe / participant de l'événement peut commenter."""
    message = _message(db, message_id, current)
    _require_participant(message.thread, current)
    comment = models.MessageComment(message=message, author_id=current.id, content=payload.content)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/messages/{message_id}/comments", response_model=list[schemas.CommentRead])
def list_message_comments(message_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Commentaires d'un message."""
    return _message(db, message_id, current).comments


@router.patch("/message-comments/{comment_id}", response_model=schemas.CommentRead)
def update_message_comment(
    comment_id: int, payload: schemas.CommentUpdate, current: CurrentUser, db: Session = Depends(get_db)
):
    """Modifie un commentaire (auteur uniquement)."""
    comment = _comment(db, comment_id, current)
    if comment.author_id != current.id:
        raise forbidden("Seul l'auteur peut modifier ce commentaire")
    comment.content = payload.content
    db.commit()
    db.refresh(comment)
    return comment


@router.delete("/message-comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message_comment(comment_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime un commentaire (auteur ou modérateur)."""
    comment = _comment(db, comment_id, current)
    _require_author_or_moderator(comment.author_id, comment.message.thread, current)
    db.delete(comment)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
