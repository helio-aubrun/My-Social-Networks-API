from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from .common import ORMModel, UserSummary


class QuestionCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=2, description="Au moins 2 réponses possibles")

    @field_validator("options")
    @classmethod
    def _clean_options(cls, options: list[str]) -> list[str]:
        cleaned = [o.strip() for o in options]
        if any(not o for o in cleaned):
            raise ValueError("Une réponse ne peut pas être vide")
        if len({o.lower() for o in cleaned}) != len(cleaned):
            raise ValueError("Les réponses d'une question doivent être distinctes")
        return cleaned


class PollCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    questions: list[QuestionCreate] = Field(min_length=1)


class PollUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    questions: list[QuestionCreate] | None = Field(
        default=None, min_length=1, description="Remplace les questions (impossible si déjà des réponses)"
    )


class OptionRead(ORMModel):
    id: int
    text: str


class QuestionRead(ORMModel):
    id: int
    text: str
    options: list[OptionRead]


class PollRead(ORMModel):
    id: int
    event_id: int
    title: str
    creator: UserSummary | None
    questions: list[QuestionRead]
    created_at: datetime


class AnswerItem(BaseModel):
    question_id: int
    option_id: int


class PollResponseSubmit(BaseModel):
    answers: list[AnswerItem] = Field(min_length=1, description="Une réponse par question")


class PollResponseRead(BaseModel):
    poll_id: int
    user_id: int
    answers: list[AnswerItem]


class OptionResult(BaseModel):
    option_id: int
    text: str
    votes: int
    percentage: float


class QuestionResult(BaseModel):
    question_id: int
    text: str
    total_votes: int
    options: list[OptionResult]


class PollResults(BaseModel):
    poll_id: int
    title: str
    respondents: int
    questions: list[QuestionResult]
