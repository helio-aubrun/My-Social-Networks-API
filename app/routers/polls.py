from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import (
    CurrentUser,
    can_view_event,
    conflict,
    is_admin,
    not_found,
    reject_nulls,
    require_event_member,
    require_event_organizer,
    require_self_or,
    unprocessable,
    viewable_event,
)

router = APIRouter(tags=["Sondages"])


def _poll(db: Session, poll_id: int, user: models.User) -> models.Poll:
    poll = db.get(models.Poll, poll_id)
    if poll is None or not can_view_event(poll.event, user):
        raise not_found("Sondage")
    return poll


def _build_questions(questions: list[schemas.QuestionCreate]) -> list[models.PollQuestion]:
    return [
        models.PollQuestion(
            text=q.text, position=i, options=[models.PollOption(text=o) for o in q.options]
        )
        for i, q in enumerate(questions)
    ]


def _answers_query(poll: models.Poll):
    return select(models.PollAnswer).where(
        models.PollAnswer.question_id.in_([q.id for q in poll.questions])
    )


@router.post("/events/{event_id}/polls", response_model=schemas.PollRead, status_code=status.HTTP_201_CREATED)
def create_poll(event_id: int, payload: schemas.PollCreate, current: CurrentUser, db: Session = Depends(get_db)):
    """Crée un sondage (1 ou plusieurs questions, au moins 2 réponses possibles par question).
    Seul un organisateur de l'événement peut créer un sondage."""
    event = viewable_event(db, event_id, current)
    require_event_organizer(event, current, "créer un sondage")
    poll = models.Poll(
        event=event, creator_id=current.id, title=payload.title,
        questions=_build_questions(payload.questions),
    )
    db.add(poll)
    db.commit()
    db.refresh(poll)
    return poll


@router.get("/events/{event_id}/polls", response_model=list[schemas.PollRead])
def list_polls(event_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Sondages d'un événement."""
    return viewable_event(db, event_id, current).polls


@router.get("/polls/{poll_id}", response_model=schemas.PollRead)
def get_poll(poll_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Détail d'un sondage avec ses questions et réponses possibles."""
    return _poll(db, poll_id, current)


@router.patch("/polls/{poll_id}", response_model=schemas.PollRead)
def update_poll(poll_id: int, payload: schemas.PollUpdate, current: CurrentUser, db: Session = Depends(get_db)):
    """Modifie le titre et/ou remplace les questions (organisateurs uniquement). Remplacer les questions
    est refusé (409) dès qu'un participant a répondu."""
    poll = _poll(db, poll_id, current)
    require_event_organizer(poll.event, current, "modifier un sondage")
    data = payload.model_dump(exclude_unset=True)
    reject_nulls(data, ("title", "questions"))
    if "title" in data:
        poll.title = data["title"]
    if payload.questions is not None:
        if db.scalar(_answers_query(poll).limit(1)) is not None:
            raise conflict("Impossible de modifier les questions : des participants ont déjà répondu")
        poll.questions = _build_questions(payload.questions)
    db.commit()
    db.refresh(poll)
    return poll


@router.delete("/polls/{poll_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_poll(poll_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime un sondage, ses questions et toutes les réponses (organisateurs uniquement)."""
    poll = _poll(db, poll_id, current)
    require_event_organizer(poll.event, current, "supprimer un sondage")
    db.delete(poll)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/polls/{poll_id}/responses", response_model=schemas.PollResponseRead)
def submit_response(
    poll_id: int, payload: schemas.PollResponseSubmit, current: CurrentUser, db: Session = Depends(get_db)
):
    """Répond au sondage au nom de l'utilisateur connecté : exactement une réponse pour chaque question.
    Réservé aux participants (et organisateurs). Renvoyer remplace la réponse précédente."""
    poll = _poll(db, poll_id, current)
    require_event_member(poll.event, current, "répondre aux sondages")

    questions = {q.id: q for q in poll.questions}
    answered = [a.question_id for a in payload.answers]
    if len(answered) != len(set(answered)):
        raise unprocessable("Une seule réponse peut être choisie par question")
    if set(answered) != set(questions):
        raise unprocessable("Il faut répondre à chaque question du sondage, et uniquement à celles-ci")
    for item in payload.answers:
        if item.option_id not in {o.id for o in questions[item.question_id].options}:
            raise unprocessable(f"La réponse {item.option_id} n'appartient pas à la question {item.question_id}")

    for previous in db.scalars(_answers_query(poll).where(models.PollAnswer.user_id == current.id)):
        db.delete(previous)
    db.flush()
    for item in payload.answers:
        db.add(models.PollAnswer(user_id=current.id, **item.model_dump()))
    db.commit()
    return schemas.PollResponseRead(poll_id=poll.id, user_id=current.id, answers=payload.answers)


@router.get("/polls/{poll_id}/responses", response_model=list[schemas.PollResponseRead])
def list_responses(poll_id: int, current: CurrentUser, user_id: int | None = None, db: Session = Depends(get_db)):
    """Réponses individuelles regroupées par participant. Les organisateurs voient toutes les réponses,
    un participant uniquement la sienne."""
    poll = _poll(db, poll_id, current)
    query = _answers_query(poll)
    if not (poll.event.is_organizer(current.id) or is_admin(current)):
        user_id = current.id
    if user_id is not None:
        query = query.where(models.PollAnswer.user_id == user_id)
    by_user: dict[int, list[schemas.AnswerItem]] = {}
    for a in db.scalars(query.order_by(models.PollAnswer.user_id, models.PollAnswer.question_id)):
        by_user.setdefault(a.user_id, []).append(
            schemas.AnswerItem(question_id=a.question_id, option_id=a.option_id)
        )
    return [schemas.PollResponseRead(poll_id=poll.id, user_id=u, answers=ans) for u, ans in by_user.items()]


@router.delete("/polls/{poll_id}/responses/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_response(poll_id: int, user_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Supprime la réponse d'un participant (le participant lui-même ou un organisateur)."""
    poll = _poll(db, poll_id, current)
    require_self_or(poll.event.is_organizer(current.id), user_id, current,
                    "Seul le participant ou un organisateur peut supprimer cette réponse")
    answers = list(db.scalars(_answers_query(poll).where(models.PollAnswer.user_id == user_id)))
    if not answers:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune réponse de cet utilisateur à ce sondage")
    for a in answers:
        db.delete(a)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/polls/{poll_id}/results", response_model=schemas.PollResults)
def poll_results(poll_id: int, current: CurrentUser, db: Session = Depends(get_db)):
    """Résultats agrégés (anonymes) : nombre de votes et pourcentage par réponse, pour chaque question."""
    poll = _poll(db, poll_id, current)
    respondents: set[int] = set()
    questions = []
    for q in poll.questions:
        counts = {o.id: len(o.answers) for o in q.options}
        respondents.update(a.user_id for o in q.options for a in o.answers)
        total = sum(counts.values())
        questions.append(
            schemas.QuestionResult(
                question_id=q.id,
                text=q.text,
                total_votes=total,
                options=[
                    schemas.OptionResult(
                        option_id=o.id, text=o.text, votes=counts[o.id],
                        percentage=round(100 * counts[o.id] / total, 1) if total else 0.0,
                    )
                    for o in q.options
                ],
            )
        )
    return schemas.PollResults(
        poll_id=poll.id, title=poll.title, respondents=len(respondents), questions=questions
    )
