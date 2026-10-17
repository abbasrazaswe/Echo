"""SQLite schema and connection lifecycle."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("profile_id", "source_hash"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), index=True)
    title: Mapped[str]
    source_hash: Mapped[str]
    date_order: Mapped[str]
    message_count: Mapped[int]
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime]


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "sequence_number"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    sequence_number: Mapped[int]
    speaker: Mapped[str | None]
    text: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime]
    raw_timestamp: Mapped[str]
    message_type: Mapped[str]
    source_type: Mapped[str]
    source_line_start: Mapped[int]
    source_line_end: Mapped[int]
    raw_record: Mapped[str] = mapped_column(Text)


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            URL.create("sqlite", database=str(path.resolve())),
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)


class SemanticIndex(Base):
    """Points to a fully built vector snapshot; original records stay in SQLite."""

    __tablename__ = "semantic_indexes"
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id"), primary_key=True)
    collection_name: Mapped[str]
    fingerprint: Mapped[str]
    model: Mapped[str]
    chunk_count: Mapped[int]


class DerivedArtifact(Base):
    """Reviewable derived content, separate from immutable imported messages."""

    __tablename__ = "derived_artifacts"
    __table_args__ = (UniqueConstraint("conversation_id", "kind", "artifact_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    kind: Mapped[str]
    artifact_key: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    source_message_ids: Mapped[list[str]] = mapped_column(JSON)
    generated_content: Mapped[str] = mapped_column(Text)
    generated_source_message_ids: Mapped[list[str]] = mapped_column(JSON)
    method: Mapped[str]
    uncertain: Mapped[bool]
    status: Mapped[str] = mapped_column(default="pending")
    revision: Mapped[int] = mapped_column(default=1)
