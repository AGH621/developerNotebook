"""SQLAlchemy ORM models for users and notebook content."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    """A registered account that owns topics and their content.

    Attributes
    ----------
    id : int
        Primary key.
    username : str
        Unique login name.
    password_hash : str
        Bcrypt hash of the user's password.
    is_admin : bool
        Whether the account may access the admin suite.
    is_guest : bool
        When true, the account is read-only and sees admin-selected starter topics.
    is_suspended : bool
        When true, login is denied for this account.
    session_version : int
        Incremented to invalidate issued session cookies (password reset, suspend).
    failed_login_count : int
        Consecutive failed password attempts since the last successful login.
    locked_until : datetime or None
        When set and in the future, login is denied until this time passes.
    topics : list of Topic
        Topics belonging to this user, ordered by application logic.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    topics: Mapped[list[Topic]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Topic(Base):
    """A named collection of developer command sections.

    Attributes
    ----------
    id : int
        Primary key.
    user_id : int
        Foreign key to the owning User.
    name : str
        Display name of the topic (e.g. "Git").
    slug : str
        URL-safe identifier, auto-generated from name. Unique per user.
    display_order : int
        Position in the user's topic list.
    user : User
        Owner of this topic.
    sections : list of Section
        Sections under this topic, ordered by display_order in queries.
    """

    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_topic_user_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(256))
    slug: Mapped[str] = mapped_column(String(256))
    display_order: Mapped[int] = mapped_column(default=0)

    user: Mapped[User] = relationship(back_populates="topics")
    sections: Mapped[list[Section]] = relationship(
        back_populates="topic",
        cascade="all, delete-orphan",
    )


class Section(Base):
    """A grouping of command entries inside a topic.

    A section with ``name`` of ``None`` is the default section for topics
    that are not subdivided.

    Attributes
    ----------
    id : int
        Primary key.
    topic_id : int
        Foreign key to the parent Topic.
    name : str or None
        Heading label; ``None`` means the default unnamed section.
    display_order : int
        Position within the topic's section list.
    notes : str or None
        Optional callout text (e.g. warnings).
    topic : Topic
        Parent topic.
    entries : list of Entry
        Command rows in this section.
    """

    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    display_order: Mapped[int] = mapped_column(default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    topic: Mapped[Topic] = relationship(back_populates="sections")
    entries: Mapped[list[Entry]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
    )


class Entry(Base):
    """One description plus command pair in a section table.

    Attributes
    ----------
    id : int
        Primary key.
    section_id : int
        Foreign key to the parent Section.
    description : str
        Short explanation of what the command does.
    command : str
        The literal command text to copy or run.
    display_order : int
        Position within the section's entry list.
    section : Section
        Parent section.
    """

    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"),
        index=True,
    )
    description: Mapped[str] = mapped_column(Text)
    command: Mapped[str] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(default=0)

    section: Mapped[Section] = relationship(back_populates="entries")


class Invitation(Base):
    """Single-use invite code for closed registration."""

    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    used_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    redeemed_by_user: Mapped[User | None] = relationship(foreign_keys=[used_by])


class InvitationRequest(Base):
    """Visitor request for a closed-registration invite."""

    __tablename__ = "invitation_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invitation_id: Mapped[int | None] = mapped_column(
        ForeignKey("invitations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewed_by])
    invitation: Mapped[Invitation | None] = relationship(foreign_keys=[invitation_id])


class StarterTopic(Base):
    """Global template topic for onboarding (not tied to a user)."""

    __tablename__ = "starter_topics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256))
    slug: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    guest_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    display_order: Mapped[int] = mapped_column(default=0)

    sections: Mapped[list[StarterSection]] = relationship(
        back_populates="topic",
        cascade="all, delete-orphan",
    )


class StarterSection(Base):
    """Section row inside the starter catalog."""

    __tablename__ = "starter_sections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("starter_topics.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    display_order: Mapped[int] = mapped_column(default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    topic: Mapped[StarterTopic] = relationship(back_populates="sections")
    entries: Mapped[list[StarterEntry]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
    )


class AppSettings(Base):
    """Singleton application settings (row ``id=1``)."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_absolute_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    session_idle_minutes: Mapped[int] = mapped_column(Integer, nullable=False)


class StarterEntry(Base):
    """Command row inside a starter catalog section."""

    __tablename__ = "starter_entries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("starter_sections.id", ondelete="CASCADE"),
        index=True,
    )
    description: Mapped[str] = mapped_column(Text)
    command: Mapped[str] = mapped_column(Text)
    display_order: Mapped[int] = mapped_column(default=0)

    section: Mapped[StarterSection] = relationship(back_populates="entries")
