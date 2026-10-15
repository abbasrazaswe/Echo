"""Profile creation, transactional imports, and historical message browsing."""

from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Conversation, Message, Profile
from app.parser.whatsapp import DateOrder, MessageRecord, ParseError, parse_whatsapp


router = APIRouter()


def session_for(request: Request):
    with request.app.state.database.sessions() as session:
        yield session


SessionDependency = Annotated[Session, Depends(session_for)]


class ProfileInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)


class ProfileOutput(ProfileInput):
    id: str


class ImportInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    transcript: str = Field(
        min_length=1, max_length=2_000_000,
        examples=["14/10/2026, 09:01 - Ali: Shall we study Python?\n14/10/2026, 09:02 - Sara: Yes, let's start with functions."],
    )
    date_order: DateOrder


class ConversationOutput(BaseModel):
    id: str
    profile_id: str
    title: str
    date_order: DateOrder
    message_count: int


class MessageOutput(MessageRecord):
    id: str
    conversation_id: str


class MessagePage(BaseModel):
    items: list[MessageOutput]
    total: int
    limit: int
    offset: int


def require_profile(session: Session, profile_id: str) -> Profile:
    profile = session.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, "Profile not found")
    return profile


def require_conversation(session: Session, profile_id: str, conversation_id: str) -> Conversation:
    require_profile(session, profile_id)
    conversation = session.get(Conversation, conversation_id)
    if conversation is None or conversation.profile_id != profile_id:
        raise HTTPException(404, "Conversation not found in this profile")
    return conversation


@router.post("/profiles", response_model=ProfileOutput, status_code=201)
def create_profile(body: ProfileInput, session: SessionDependency):
    profile = Profile(name=body.name)
    session.add(profile)
    session.commit()
    return profile


@router.get("/profiles", response_model=list[ProfileOutput])
def list_profiles(session: SessionDependency):
    return session.scalars(select(Profile).order_by(Profile.created_at, Profile.id)).all()


@router.post("/profiles/{profile_id}/imports", response_model=ConversationOutput, status_code=201)
def import_transcript(profile_id: str, body: ImportInput, session: SessionDependency):
    require_profile(session, profile_id)
    normalized = body.transcript.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    duplicate_query = select(Conversation).where(
        Conversation.profile_id == profile_id, Conversation.source_hash == digest,
    )
    if session.scalar(duplicate_query):
        raise HTTPException(409, "This transcript is already imported into this profile")
    try:
        records = parse_whatsapp(normalized, date_order=body.date_order)
    except ParseError as error:
        raise HTTPException(422, str(error)) from error
    conversation = Conversation(
        profile_id=profile_id, title=body.title, source_hash=digest,
        date_order=body.date_order, message_count=len(records),
        started_at=min(record.timestamp for record in records),
        ended_at=max(record.timestamp for record in records),
    )
    try:
        session.add(conversation)
        session.flush()
        session.add_all([
            Message(conversation_id=conversation.id, **record.model_dump())
            for record in records
        ])
        session.commit()
    except IntegrityError as error:
        session.rollback()
        if session.scalar(duplicate_query):
            raise HTTPException(409, "This transcript is already imported into this profile") from error
        raise
    return conversation


@router.get("/profiles/{profile_id}/conversations", response_model=list[ConversationOutput])
def list_conversations(profile_id: str, session: SessionDependency):
    require_profile(session, profile_id)
    return session.scalars(select(Conversation).where(
        Conversation.profile_id == profile_id,
    ).order_by(Conversation.started_at, Conversation.id)).all()


@router.get("/profiles/{profile_id}/messages", response_model=MessagePage)
def list_messages(
    profile_id: str, session: SessionDependency,
    conversation_id: str | None = None,
    q: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    require_profile(session, profile_id)
    filters = [Conversation.profile_id == profile_id]
    if conversation_id:
        require_conversation(session, profile_id, conversation_id)
        filters.append(Message.conversation_id == conversation_id)
    if q:
        filters.append(Message.text.contains(q, autoescape=True))
    query = select(Message).join(Conversation).where(*filters)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    items = session.scalars(query.order_by(
        Conversation.started_at, Conversation.id, Message.sequence_number,
    ).limit(limit).offset(offset)).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/profiles/{profile_id}/conversations/{conversation_id}/export", response_model=list[MessageOutput])
def export_conversation(profile_id: str, conversation_id: str, session: SessionDependency):
    require_conversation(session, profile_id, conversation_id)
    return session.scalars(select(Message).where(
        Message.conversation_id == conversation_id,
    ).order_by(Message.sequence_number)).all()
