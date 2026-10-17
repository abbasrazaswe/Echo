"""Generate, inspect, and review derived records without editing source messages."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.api import MessageOutput, SessionDependency, require_conversation, require_profile
from app.artifacts import METHOD, candidates
from app.database import Conversation, DerivedArtifact, Message


Kind = Literal["summary", "person", "event", "topic"]
Status = Literal["pending", "confirmed", "corrected", "rejected"]
router = APIRouter(prefix="/profiles/{profile_id}/artifacts", tags=["Summaries and references"])


class ArtifactOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    conversation_id: str
    kind: Kind
    content: str
    source_message_ids: list[str]
    generated_content: str
    generated_source_message_ids: list[str]
    method: str
    uncertain: bool
    status: Status
    revision: int


class ArtifactDetail(ArtifactOutput):
    sources: list[MessageOutput]
    generated_sources: list[MessageOutput]


class ArtifactPage(BaseModel):
    items: list[ArtifactOutput]
    total: int
    limit: int
    offset: int


class GenerationResult(BaseModel):
    created: int
    refreshed: int
    preserved: int
    method: str = METHOD


class ReviewInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    revision: int = Field(ge=1)
    status: Literal["confirmed", "corrected", "rejected"]
    content: str | None = Field(default=None, min_length=1, max_length=10_000)
    source_message_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def check_correction(self):
        changes = self.content is not None or self.source_message_ids is not None
        if changes != (self.status == "corrected"):
            raise ValueError("Use corrected with content and/or source IDs; confirm/reject without changing fields.")
        return self


def require_artifact(session, profile_id: str, artifact_id: str) -> DerivedArtifact:
    require_profile(session, profile_id)
    artifact = session.scalar(select(DerivedArtifact).join(Conversation).where(
        Conversation.profile_id == profile_id, DerivedArtifact.id == artifact_id,
    ))
    if artifact is None:
        raise HTTPException(404, "Artifact not found in this profile")
    return artifact


def detail(session, artifact: DerivedArtifact) -> dict:
    def sources(ids):
        return list(session.scalars(select(Message).where(
            Message.conversation_id == artifact.conversation_id, Message.id.in_(ids),
        ).order_by(Message.sequence_number)))
    return {
        **ArtifactOutput.model_validate(artifact).model_dump(),
        "sources": sources(artifact.source_message_ids),
        "generated_sources": sources(artifact.generated_source_message_ids),
    }


@router.post("/generate", response_model=GenerationResult)
def generate(profile_id: str, session: SessionDependency, conversation_id: str | None = None):
    require_profile(session, profile_id)
    query = select(Conversation).where(Conversation.profile_id == profile_id)
    if conversation_id is not None:
        require_conversation(session, profile_id, conversation_id)
        query = query.where(Conversation.id == conversation_id)
    counts = {"created": 0, "refreshed": 0, "preserved": 0}
    try:
        for conversation in session.scalars(query.order_by(Conversation.id)).all():
            messages = list(session.scalars(select(Message).where(
                Message.conversation_id == conversation.id,
            ).order_by(Message.sequence_number)))
            existing = {(item.kind, item.artifact_key): item for item in session.scalars(
                select(DerivedArtifact).where(DerivedArtifact.conversation_id == conversation.id),
            )}
            for candidate in candidates(messages):
                artifact = existing.get((candidate.kind, candidate.key))
                values = {
                    "content": candidate.content, "generated_content": candidate.content,
                    "source_message_ids": candidate.source_ids,
                    "generated_source_message_ids": candidate.source_ids,
                    "method": METHOD, "uncertain": candidate.uncertain,
                }
                if artifact is None:
                    session.add(DerivedArtifact(
                        conversation_id=conversation.id, kind=candidate.kind,
                        artifact_key=candidate.key, **values,
                    ))
                    counts["created"] += 1
                elif artifact.status != "pending":
                    counts["preserved"] += 1
                else:
                    result = session.execute(update(DerivedArtifact).where(
                        DerivedArtifact.id == artifact.id, DerivedArtifact.status == "pending",
                        DerivedArtifact.revision == artifact.revision,
                    ).values(**values, revision=artifact.revision + 1))
                    counts["refreshed" if result.rowcount else "preserved"] += 1
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "Artifacts changed during generation. Retry the request.") from error
    return counts


@router.get("", response_model=ArtifactPage)
def list_artifacts(
    profile_id: str, session: SessionDependency, kind: Kind | None = None,
    status: Status | None = None, conversation_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
):
    require_profile(session, profile_id)
    query = select(DerivedArtifact).join(Conversation).where(Conversation.profile_id == profile_id)
    if conversation_id is not None:
        require_conversation(session, profile_id, conversation_id)
        query = query.where(DerivedArtifact.conversation_id == conversation_id)
    if kind is not None:
        query = query.where(DerivedArtifact.kind == kind)
    if status is not None:
        query = query.where(DerivedArtifact.status == status)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    items = session.scalars(query.order_by(
        DerivedArtifact.conversation_id, DerivedArtifact.kind, DerivedArtifact.artifact_key,
    ).limit(limit).offset(offset)).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{artifact_id}", response_model=ArtifactDetail)
def inspect(profile_id: str, artifact_id: str, session: SessionDependency):
    return detail(session, require_artifact(session, profile_id, artifact_id))


@router.patch("/{artifact_id}", response_model=ArtifactDetail)
def review(profile_id: str, artifact_id: str, body: ReviewInput, session: SessionDependency):
    artifact = require_artifact(session, profile_id, artifact_id)
    values = {"status": body.status, "revision": body.revision + 1}
    if body.content is not None:
        values["content"] = body.content
    if body.source_message_ids is not None:
        ids = list(dict.fromkeys(body.source_message_ids))
        count = session.scalar(select(func.count()).select_from(Message).where(
            Message.conversation_id == artifact.conversation_id, Message.id.in_(ids),
        ))
        if count != len(ids):
            raise HTTPException(422, "All source IDs must belong to the artifact's conversation")
        values["source_message_ids"] = ids
    result = session.execute(update(DerivedArtifact).where(
        DerivedArtifact.id == artifact.id, DerivedArtifact.revision == body.revision,
    ).values(**values))
    if not result.rowcount:
        session.rollback()
        raise HTTPException(409, "Artifact was changed. Reload it and review the latest revision.")
    session.commit()
    session.refresh(artifact)
    return detail(session, artifact)
