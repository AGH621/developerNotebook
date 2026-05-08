"""SQLAlchemy ORM models for users and notebook content."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
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
    topics : list of Topic
        Topics belonging to this user, ordered by application logic.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))

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
