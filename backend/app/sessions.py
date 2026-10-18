"""Persistent new conversations and explicitly saved user statements."""

import re
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from app.api import SessionDependency, require_profile
from app.artifacts import tokens
from app.database import ChatSession, ChatTurn, Database, LiveMemory, TurnStyle, new_id


router = APIRouter(prefix="/profiles/{profile_id}", tags=["Sessions and live memory"])


class SessionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(default="New chat", min_length=1, max_length=200)


class SessionOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    profile_id: str
    title: str
    revision: int
    turn_count: int
    topic: str | None
    created_at: datetime


class MemoryOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    session_id: str
    source_turn_id: str
    content: str
    active: bool
    created_at: datetime
    source: str = "live"


def require_session(session, profile_id, session_id):
    record = session.get(ChatSession, session_id)
    if record is None or record.profile_id != profile_id:
        raise HTTPException(404, "Chat session not found in this profile")
    return record


@router.post("/sessions", response_model=SessionOutput, status_code=201)
def create_session(profile_id: str, body: SessionInput, session: SessionDependency):
    require_profile(session, profile_id)
    record = ChatSession(profile_id=profile_id, title=body.title)
    session.add(record)
    session.commit()
    return record


@router.get("/sessions", response_model=list[SessionOutput])
def list_sessions(profile_id: str, session: SessionDependency, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    require_profile(session, profile_id)
    return session.scalars(select(ChatSession).where(ChatSession.profile_id == profile_id).order_by(
        ChatSession.created_at, ChatSession.id,
    ).limit(limit).offset(offset)).all()


@router.get("/sessions/{session_id}", response_model=SessionOutput)
def inspect_session(profile_id: str, session_id: str, session: SessionDependency):
    require_profile(session, profile_id)
    return require_session(session, profile_id, session_id)


class TurnOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    session_id: str
    sequence_number: int
    role: str
    content: str
    status: str | None
    citations: list[dict]
    live_citations: list[dict]
    follow_up_question: str | None
    model: str | None
    created_at: datetime
    style: dict | None = None


class TurnPage(BaseModel):
    items: list[TurnOutput]
    total: int
    limit: int
    offset: int


@router.get("/sessions/{session_id}/turns", response_model=TurnPage)
def list_turns(profile_id: str, session_id: str, session: SessionDependency,
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    require_profile(session, profile_id)
    record = require_session(session, profile_id, session_id)
    items = session.scalars(select(ChatTurn).where(ChatTurn.session_id == session_id).order_by(
        ChatTurn.sequence_number,
    ).limit(limit).offset(offset)).all()
    styles = {style.turn_id: {"revision": style.revision, "settings": style.settings}
              for style in session.scalars(select(TurnStyle).where(TurnStyle.turn_id.in_([item.id for item in items])))}
    rows = [{**TurnOutput.model_validate(item).model_dump(), "style": styles.get(item.id)} for item in items]
    return {"items": rows, "total": record.turn_count, "limit": limit, "offset": offset}


class MemoryPage(BaseModel):
    items: list[MemoryOutput]
    total: int
    limit: int
    offset: int


@router.get("/live-memories", response_model=MemoryPage)
def list_memories(profile_id: str, session: SessionDependency, active: bool | None = None,
                  limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    require_profile(session, profile_id)
    query = select(LiveMemory).join(ChatSession).where(ChatSession.profile_id == profile_id)
    if active is not None:
        query = query.where(LiveMemory.active == active)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    items = session.scalars(query.order_by(LiveMemory.created_at, LiveMemory.id).limit(limit).offset(offset)).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


class MemoryReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool


@router.patch("/live-memories/{memory_id}", response_model=MemoryOutput)
def review_memory(profile_id: str, memory_id: str, body: MemoryReview, session: SessionDependency):
    require_profile(session, profile_id)
    memory = session.scalar(select(LiveMemory).join(ChatSession).where(
        LiveMemory.id == memory_id, ChatSession.profile_id == profile_id,
    ))
    if memory is None:
        raise HTTPException(404, "Live memory not found in this profile")
    memory.active = body.active
    session.commit()
    return memory


@dataclass
class SessionContext:
    record: ChatSession
    history: list[dict]
    questions: list[str]
    memories: list[LiveMemory]
    trimmed: bool


def load_context(database: Database, profile_id: str, session_id: str, revision: int) -> SessionContext:
    with database.sessions() as session:
        record = require_session(session, profile_id, session_id)
        if record.revision != revision:
            raise HTTPException(409, "Session changed. Reload its revision before sending another message.")
        turns = list(session.scalars(select(ChatTurn).where(ChatTurn.session_id == session_id).order_by(
            ChatTurn.sequence_number.desc(),
        ).limit(8)))
        turns.reverse()
        history = []
        trimmed = record.turn_count > len(turns)
        for turn in turns:
            text = turn.content + ("\n" + turn.follow_up_question if turn.follow_up_question else "")
            trimmed = trimmed or len(text) > 1000
            history.append({"role": turn.role, "content": text[:1000]})
        questions = list(session.scalars(select(ChatTurn.follow_up_question).where(
            ChatTurn.session_id == session_id, ChatTurn.follow_up_question.is_not(None),
        ).order_by(ChatTurn.sequence_number.desc()).limit(10)))
        memories = list(session.scalars(select(LiveMemory).join(ChatSession).where(
            ChatSession.profile_id == profile_id, LiveMemory.active.is_(True),
        ).order_by(LiveMemory.created_at.desc(), LiveMemory.id.desc()).limit(20)))
        return SessionContext(record, history, questions, memories, trimmed)


def normalize_question(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def is_follow_up(text: str) -> bool:
    return bool(re.fullmatch(
        r"(?:tell me more|go on|continue|why|how|and then|what happened next|what about (?:it|that|this)|where was it|when was it)[?.!\s]*",
        text.strip(), re.IGNORECASE,
    ))


def retrieval_query(message: str, context: SessionContext | None) -> str:
    if context and context.record.topic_query and is_follow_up(message):
        available = 220 - len(message) - 3
        return context.record.topic_query[:available] + " | " + message
    return message


def persist_exchange(database: Database, profile_id: str, state: SessionContext, message: str,
                     result: dict, remember: list[str]) -> dict:
    topic_query = state.record.topic_query if is_follow_up(message) else message
    topic = " ".join(dict.fromkeys(tokens(topic_query or "")))[:120] or state.record.topic
    revision = state.record.revision + 1
    with database.sessions.begin() as session:
        values = {"revision": revision, "turn_count": state.record.turn_count + 2,
                  "topic": topic, "topic_query": topic_query}
        if result["follow_up_question"]:
            values["last_follow_up_revision"] = revision
        changed = session.execute(update(ChatSession).where(
            ChatSession.id == state.record.id, ChatSession.profile_id == profile_id,
            ChatSession.revision == state.record.revision,
        ).values(**values))
        if not changed.rowcount:
            raise HTTPException(409, "Session changed while generating the reply. Reload before retrying.")
        cited = {citation.memory_id for citation in result["live_citations"]}
        if cited:
            active = set(session.scalars(select(LiveMemory.id).join(ChatSession).where(
                ChatSession.profile_id == profile_id, LiveMemory.active.is_(True), LiveMemory.id.in_(cited),
            )))
            if active != cited:
                raise HTTPException(409, "Live memory changed while generating the reply. Retry with current context.")
        user_turn = ChatTurn(id=new_id(), session_id=state.record.id, sequence_number=state.record.turn_count + 1,
                             role="user", content=message)
        session.add(user_turn)
        session.flush()
        assistant = ChatTurn(
            id=new_id(), session_id=state.record.id, sequence_number=state.record.turn_count + 2,
            role="assistant", content=result["answer"], status=result["status"],
            citations=[citation.model_dump() for citation in result["citations"]],
            live_citations=[citation.model_dump() for citation in result["live_citations"]],
            follow_up_question=result["follow_up_question"], model=result["model"],
        )
        session.add(assistant)
        if result.get("style"):
            session.flush()
            session.add(TurnStyle(turn_id=assistant.id, **result["style"]))
        saved_ids = []
        for fact in dict.fromkeys(remember):
            memory = LiveMemory(id=new_id(), session_id=state.record.id, source_turn_id=user_turn.id, content=fact)
            session.add(memory)
            saved_ids.append(memory.id)
    return {**result, "session_id": state.record.id, "session_revision": revision,
            "topic": topic, "saved_memory_ids": saved_ids}
