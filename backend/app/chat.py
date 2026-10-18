"""Retrieval → bounded evidence → model → citation validation."""

import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator
from sqlalchemy import select

from app.api import SearchHit, SessionDependency, require_profile
from app.database import Conversation, DerivedArtifact
from app.llm import Citation, LiveCitation, LLMError, LLMProvider, ModelAnswer, ModelRefused
from app.retrieval import IndexRequired, RetrievalService, RetrievalUnavailable
from app.sessions import MemoryOutput, SessionContext, is_follow_up, load_context, normalize_question, persist_exchange, retrieval_query
from app.style import AppliedStyle, applied_style


router = APIRouter(tags=["Grounded chat"])
UNCERTAINTY = "I couldn't find enough supporting evidence in the retrieved conversation excerpts to answer that."
INSTRUCTIONS = (Path(__file__).parent / "prompts/grounded_chat.txt").read_text()


class RecentTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    profile_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=220)
    recent_turns: list[RecentTurn] = Field(default_factory=list, max_length=8)
    min_score: float = Field(default=0.3, ge=0, le=1)
    session_id: str | None = Field(default=None, min_length=1)
    session_revision: int | None = Field(default=None, ge=0)
    remember: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=220)]] = Field(default_factory=list, max_length=3)
    allow_follow_up: bool = True

    @model_validator(mode="after")
    def validate_session_request(self):
        if (self.session_id is None) != (self.session_revision is None):
            raise ValueError("Supply both session_id and session_revision, or neither.")
        if self.session_id and self.recent_turns:
            raise ValueError("Session history is loaded from storage; do not supply recent_turns.")
        if self.remember and (not self.session_id or any(fact not in self.message for fact in self.remember)):
            raise ValueError("Remember requests require a session and exact excerpts from the current message.")
        return self


class ChatOutput(BaseModel):
    answer: str
    status: Literal["answered", "insufficient_evidence", "refused", "memory_saved"]
    citations: list[Citation]
    context: list[SearchHit]
    summary_ids: list[str]
    history_trimmed: bool
    model: str | None
    live_citations: list[LiveCitation]
    live_memory_context: list[MemoryOutput]
    follow_up_question: str | None
    session_id: str | None = None
    session_revision: int | None = None
    topic: str | None = None
    saved_memory_ids: list[str] = Field(default_factory=list)
    retrieval_query: str
    style: AppliedStyle | None = None


class ChatService:
    def __init__(self, retrieval: RetrievalService, provider: LLMProvider):
        self.retrieval = retrieval
        self.provider = provider

    def reply(self, body: ChatInput) -> dict:
        state = load_context(self.retrieval.database, body.profile_id, body.session_id, body.session_revision) if body.session_id else None
        result = self.generate_reply(body, state)
        if state:
            return persist_exchange(self.retrieval.database, body.profile_id, state, body.message, result, body.remember)
        return result

    def generate_reply(self, body: ChatInput, state: SessionContext | None) -> dict:
        query = retrieval_query(body.message, state)
        base = {"context": [], "summary_ids": [], "history_trimmed": False,
                "model": None, "citations": [], "live_citations": [],
                "live_memory_context": [], "follow_up_question": None, "retrieval_query": query, "style": None}
        if body.remember:
            return {**base, "answer": "I've saved the information you explicitly asked me to remember as live memory.", "status": "memory_saved"}
        # New sessions can use live memory before any historical transcript is imported.
        with self.retrieval.database.sessions() as session:
            has_history = session.scalar(select(Conversation.id).where(Conversation.profile_id == body.profile_id).limit(1)) is not None
        hits = self.retrieval.search(body.profile_id, query, limit=5, min_score=body.min_score)["items"] if has_history or state is None else []
        history = []
        remaining = 4000
        raw_history = state.history if state else [turn.model_dump() for turn in body.recent_turns]
        for turn in reversed(raw_history):
            if len(turn["content"]) > remaining:
                break
            history.append(turn)
            remaining -= len(turn["content"])
        history.reverse()
        memories = []
        memory_budget = 4000
        for memory in state.memories if state else []:
            if len(memory.content) > memory_budget:
                break
            memories.append(memory)
            memory_budget -= len(memory.content)
        output = {
            **base, "context": hits, "history_trimmed": len(history) != len(raw_history) or bool(state and state.trimmed),
            "live_memory_context": [MemoryOutput.model_validate(memory).model_dump() for memory in memories],
        }
        if not hits and not memories:
            return {**output, "answer": UNCERTAINTY, "status": "insufficient_evidence"}
        evidence = []
        allowed: dict[str, list[str]] = {}
        for hit in hits:
            sources = {message.id: message for message in hit["messages"]}
            for span in hit["spans"]:
                source = sources[span["message_id"]]
                text = source.text[span["start_char"]:span["end_char"]]
                allowed.setdefault(source.id, []).append(text)
                evidence.append({
                    "message_id": source.id, "speaker": (source.speaker or "Unknown")[:80],
                    "timestamp": source.timestamp.isoformat(), "text": text,
                    "start_char": span["start_char"], "end_char": span["end_char"],
                })
        hints = []
        with self.retrieval.database.sessions() as session:
            summaries = session.scalars(select(DerivedArtifact).where(
                DerivedArtifact.conversation_id.in_({hit["conversation_id"] for hit in hits}),
                DerivedArtifact.kind == "summary", DerivedArtifact.status.in_(["confirmed", "corrected"]),
            ).order_by(DerivedArtifact.id))
            for summary in summaries:
                if set(summary.source_message_ids).issubset(allowed):
                    hints.append({"id": summary.id, "text": summary.content[:600], "status": summary.status})
                    if len(hints) == 3:
                        break
        output["summary_ids"] = [hint["id"] for hint in hints]
        with self.retrieval.database.sessions() as session:
            output["style"] = applied_style(session, body.profile_id)
        questions = state.questions if state else []
        follow_up_allowed = body.allow_follow_up and (state is None or state.record.revision - state.record.last_follow_up_revision >= 2)
        context = json.dumps({
            "question": body.message, "recent_turns": history,
            "historical_excerpts": evidence, "reviewed_summary_hints": hints,
            "current_topic": state.record.topic if state else None,
            "live_memory": [{"memory_id": memory.id, "text": memory.content, "source": "live",
                             "source_turn_id": memory.source_turn_id, "session_id": memory.session_id} for memory in memories],
            "follow_up_allowed": follow_up_allowed, "previous_follow_up_questions": questions,
            "presentation_style": output["style"]["settings"] if output["style"] else None,
        }, ensure_ascii=False)
        try:
            answer = ModelAnswer.model_validate(self.provider.generate(INSTRUCTIONS, context))
        except ModelRefused:
            return {**output, "answer": "I can't help with that request.", "status": "refused", "model": self.provider.model, "style": None}
        except ValidationError as error:
            raise LLMError(502, "The model returned an invalid structured reply.") from error
        output["model"] = self.provider.model
        if answer.insufficient_evidence:
            return {**output, "answer": UNCERTAINTY, "status": "insufficient_evidence", "style": None}
        live_allowed = {memory.id: memory.content for memory in memories}
        if (not answer.citations and not answer.live_citations) or any(
            citation.message_id not in allowed or not any(citation.quote in text for text in allowed[citation.message_id])
            for citation in answer.citations
        ) or any(citation.memory_id not in live_allowed or citation.quote not in live_allowed[citation.memory_id]
                 for citation in answer.live_citations):
            raise LLMError(502, "The model reply failed source validation. No generated answer was returned.")
        unique = list({(citation.message_id, citation.quote): citation for citation in answer.citations}.values())
        live_unique = list({(citation.memory_id, citation.quote): citation for citation in answer.live_citations}.values())
        question = answer.follow_up_question
        previous = questions + [turn["content"] for turn in history if turn["role"] == "assistant"] + [body.message]
        if not follow_up_allowed or not question or not normalize_question(question) or any(
            normalize_question(question) in normalize_question(old) for old in previous
        ):
            question = None
        return {**output, "answer": answer.answer, "status": "answered", "citations": unique,
                "live_citations": live_unique, "follow_up_question": question}


@router.post("/chat", response_model=ChatOutput)
def chat(body: ChatInput, request: Request, session: SessionDependency):
    require_profile(session, body.profile_id)
    try:
        return request.app.state.chat.reply(body)
    except IndexRequired as error:
        raise HTTPException(409, str(error)) from error
    except RetrievalUnavailable as error:
        raise HTTPException(503, str(error)) from error
    except LLMError as error:
        headers = {"Retry-After": error.retry_after} if error.retry_after else None
        raise HTTPException(error.status_code, str(error), headers=headers) from error
