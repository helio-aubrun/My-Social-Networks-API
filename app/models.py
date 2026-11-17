import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _association(name: str, left: str, right: str = "users") -> Table:
    return Table(
        name,
        Base.metadata,
        Column(f"{left[:-1]}_id", ForeignKey(f"{left}.id", ondelete="CASCADE"), primary_key=True),
        Column("user_id", ForeignKey(f"{right}.id", ondelete="CASCADE"), primary_key=True),
    )


event_organizers = _association("event_organizers", "events")
event_participants = _association("event_participants", "events")
group_admins = _association("group_admins", "groups")
group_members = _association("group_members", "groups")


class Visibility(str, enum.Enum):
    public = "public"
    private = "private"


class Role(str, enum.Enum):
    user = "user"
    admin = "admin"


class GroupType(str, enum.Enum):
    public = "public"
    private = "private"
    secret = "secret"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.user)
    bio: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(String(500))

    organized_events: Mapped[list["Event"]] = relationship(
        secondary=event_organizers, back_populates="organizers"
    )
    participating_events: Mapped[list["Event"]] = relationship(
        secondary=event_participants, back_populates="participants"
    )
    administered_groups: Mapped[list["Group"]] = relationship(
        secondary=group_admins, back_populates="admins"
    )
    groups: Mapped[list["Group"]] = relationship(secondary=group_members, back_populates="members")


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(500))
    cover_photo: Mapped[str | None] = mapped_column(String(500))
    type: Mapped[GroupType] = mapped_column(Enum(GroupType), default=GroupType.public)
    allow_member_posts: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_member_events: Mapped[bool] = mapped_column(Boolean, default=True)

    admins: Mapped[list[User]] = relationship(secondary=group_admins, back_populates="administered_groups")
    members: Mapped[list[User]] = relationship(secondary=group_members, back_populates="groups")
    events: Mapped[list["Event"]] = relationship(back_populates="group")
    thread: Mapped["Thread | None"] = relationship(back_populates="group", cascade="all, delete-orphan")

    def is_member(self, user_id: int) -> bool:
        return any(u.id == user_id for u in self.members)

    def is_admin(self, user_id: int) -> bool:
        return any(u.id == user_id for u in self.admins)


class Event(TimestampMixin, Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text)
    start_date: Mapped[datetime] = mapped_column(DateTime)
    end_date: Mapped[datetime] = mapped_column(DateTime)
    location: Mapped[str] = mapped_column(String(300))
    cover_photo: Mapped[str | None] = mapped_column(String(500))
    visibility: Mapped[Visibility] = mapped_column(Enum(Visibility), default=Visibility.public)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    ticketing_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    shopping_list_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    carpool_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    organizers: Mapped[list[User]] = relationship(
        secondary=event_organizers, back_populates="organized_events"
    )
    participants: Mapped[list[User]] = relationship(
        secondary=event_participants, back_populates="participating_events"
    )
    group: Mapped[Group | None] = relationship(back_populates="events")
    thread: Mapped["Thread | None"] = relationship(back_populates="event", cascade="all, delete-orphan")
    albums: Mapped[list["Album"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    polls: Mapped[list["Poll"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    ticket_types: Mapped[list["TicketType"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    shopping_items: Mapped[list["ShoppingItem"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    carpools: Mapped[list["CarpoolOffer"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

    def is_organizer(self, user_id: int) -> bool:
        return any(u.id == user_id for u in self.organizers)

    def is_member(self, user_id: int) -> bool:
        return self.is_organizer(user_id) or any(u.id == user_id for u in self.participants)


class Thread(Base):
    __tablename__ = "threads"
    __table_args__ = (
        CheckConstraint("(group_id IS NULL) <> (event_id IS NULL)", name="ck_thread_single_parent"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(String(200))
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), unique=True
    )
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    group: Mapped[Group | None] = relationship(back_populates="thread")
    event: Mapped[Event | None] = relationship(back_populates="thread")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)

    thread: Mapped[Thread] = relationship(back_populates="messages")
    author: Mapped[User] = relationship()
    comments: Mapped[list["MessageComment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", order_by="MessageComment.id"
    )


class MessageComment(TimestampMixin, Base):
    __tablename__ = "message_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)

    message: Mapped[Message] = relationship(back_populates="comments")
    author: Mapped[User] = relationship()


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    event: Mapped[Event] = relationship(back_populates="albums")
    photos: Mapped[list["Photo"]] = relationship(
        back_populates="album", cascade="all, delete-orphan", order_by="Photo.id"
    )

    @property
    def photo_count(self) -> int:
        return len(self.photos)


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    album_id: Mapped[int] = mapped_column(ForeignKey("albums.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(500))
    caption: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    album: Mapped[Album] = relationship(back_populates="photos")
    author: Mapped[User] = relationship()
    comments: Mapped[list["PhotoComment"]] = relationship(
        back_populates="photo", cascade="all, delete-orphan", order_by="PhotoComment.id"
    )


class PhotoComment(TimestampMixin, Base):
    __tablename__ = "photo_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    photo_id: Mapped[int] = mapped_column(ForeignKey("photos.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)

    photo: Mapped[Photo] = relationship(back_populates="comments")
    author: Mapped[User] = relationship()


class Poll(Base):
    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    event: Mapped[Event] = relationship(back_populates="polls")
    creator: Mapped[User | None] = relationship()
    questions: Mapped[list["PollQuestion"]] = relationship(
        back_populates="poll", cascade="all, delete-orphan", order_by="PollQuestion.position"
    )


class PollQuestion(Base):
    __tablename__ = "poll_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)

    poll: Mapped[Poll] = relationship(back_populates="questions")
    options: Mapped[list["PollOption"]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="PollOption.id"
    )


class PollOption(Base):
    __tablename__ = "poll_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("poll_questions.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(String(300))

    question: Mapped[PollQuestion] = relationship(back_populates="options")
    answers: Mapped[list["PollAnswer"]] = relationship(
        back_populates="option", cascade="all, delete-orphan"
    )


class PollAnswer(Base):
    __tablename__ = "poll_answers"
    __table_args__ = (UniqueConstraint("question_id", "user_id", name="uq_one_answer_per_question"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("poll_questions.id", ondelete="CASCADE"))
    option_id: Mapped[int] = mapped_column(ForeignKey("poll_options.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    option: Mapped[PollOption] = relationship(back_populates="answers")


class TicketType(Base):
    __tablename__ = "ticket_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    event: Mapped[Event] = relationship(back_populates="ticket_types")
    tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="ticket_type", cascade="all, delete-orphan"
    )

    @property
    def sold(self) -> int:
        return len(self.tickets)

    @property
    def remaining(self) -> int:
        return max(self.quantity - self.sold, 0)


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("event_id", "email", name="uq_one_ticket_per_person"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_type_id: Mapped[int] = mapped_column(ForeignKey("ticket_types.id", ondelete="CASCADE"))
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255))
    street: Mapped[str] = mapped_column(String(255))
    postal_code: Mapped[str] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(100))
    purchased_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    ticket_type: Mapped[TicketType] = relationship(back_populates="tickets")


class ShoppingItem(Base):
    __tablename__ = "shopping_items"
    __table_args__ = (UniqueConstraint("event_id", "name_key", name="uq_item_per_event"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)
    arrival_time: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    event: Mapped[Event] = relationship(back_populates="shopping_items")
    user: Mapped[User] = relationship()


class CarpoolOffer(Base):
    __tablename__ = "carpool_offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    departure_location: Mapped[str] = mapped_column(String(300))
    departure_time: Mapped[datetime] = mapped_column(DateTime)
    price: Mapped[float] = mapped_column(Float)
    seats: Mapped[int] = mapped_column(Integer)
    max_detour_minutes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    event: Mapped[Event] = relationship(back_populates="carpools")
    driver: Mapped[User] = relationship()
    bookings: Mapped[list["CarpoolBooking"]] = relationship(
        back_populates="offer", cascade="all, delete-orphan"
    )

    @property
    def remaining_seats(self) -> int:
        return max(self.seats - len(self.bookings), 0)

    @property
    def passengers(self) -> list[User]:
        return [b.passenger for b in self.bookings]


class CarpoolBooking(Base):
    __tablename__ = "carpool_bookings"
    __table_args__ = (UniqueConstraint("offer_id", "passenger_id", name="uq_one_booking_per_offer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("carpool_offers.id", ondelete="CASCADE"))
    passenger_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    offer: Mapped[CarpoolOffer] = relationship(back_populates="bookings")
    passenger: Mapped[User] = relationship()
