"""Retrieval → bounded evidence → model → citation validation."""

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.api import SearchHit, SessionDependency, require_profile
from app.database import DerivedArtifact
from app.llm import Citation, LLMError, LLMProvider, ModelAnswer, ModelRefused
from app.retrieval import IndexRequired, RetrievalService, RetrievalUnavailable


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


class ChatOutput(BaseModel):
    answer: str
    status: Literal["answered", "insufficient_evidence", "refused"]
    citations: list[Citation]
    context: list[SearchHit]
    summary_ids: list[str]
    history_trimmed: bool
    model: str | None


class ChatService:
    def __init__(self, retrieval: RetrievalService, provider: LLMProvider):
        self.retrieval = retrieval
        self.provider = provider

    def reply(self, body: ChatInput) -> dict:
        hits = self.retrieval.search(body.profile_id, body.message, limit=5, min_score=body.min_score)["items"]
        history = []
        remaining = 4000
        for turn in reversed(body.recent_turns):
            if len(turn.content) > remaining:
                break
            history.append(turn.model_dump())
            remaining -= len(turn.content)
        history.reverse()
        output = {
            "context": hits, "summary_ids": [], "history_trimmed": len(history) != len(body.recent_turns),
            "model": None, "citations": [],
        }
        if not hits:
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
        context = json.dumps({
            "question": body.message, "recent_turns": history,
            "historical_excerpts": evidence, "reviewed_summary_hints": hints,
        }, ensure_ascii=False)
        try:
            answer = ModelAnswer.model_validate(self.provider.generate(INSTRUCTIONS, context))
        except ModelRefused:
            return {**output, "answer": "I can't help with that request.", "status": "refused", "model": self.provider.model}
        except ValidationError as error:
            raise LLMError(502, "The model returned an invalid structured reply.") from error
        output["model"] = self.provider.model
        if answer.insufficient_evidence:
            return {**output, "answer": UNCERTAINTY, "status": "insufficient_evidence"}
        if not answer.citations or any(
            citation.message_id not in allowed or not any(citation.quote in text for text in allowed[citation.message_id])
            for citation in answer.citations
        ):
            raise LLMError(502, "The model reply failed source validation. No generated answer was returned.")
        unique = list({(citation.message_id, citation.quote): citation for citation in answer.citations}.values())
        return {**output, "answer": answer.answer, "status": "answered", "citations": unique}


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
