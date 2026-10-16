"""Rebuildable semantic snapshots with source-message provenance."""

import json
import logging
import math
import re
from dataclasses import dataclass
from functools import cached_property
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Protocol
from uuid import uuid4

from sqlalchemy import select

from app.database import Conversation, Database, Message, SemanticIndex


logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbeddings:
    model = "onnx/all-MiniLM-L6-v2"

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path

    @cached_property
    def function(self):
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

        function = ONNXMiniLM_L6_V2()
        function.ort.disable_telemetry_events()
        function.DOWNLOAD_PATH = self.cache_path
        return function

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, vector)) for vector in self.function(texts)]


class IndexRequired(ValueError):
    pass


class RetrievalUnavailable(RuntimeError):
    pass


@dataclass
class Chunk:
    text: str
    conversation_id: str
    spans: list[dict]

    @property
    def id(self) -> str:
        return sha256(json.dumps([self.conversation_id, self.text, self.spans], sort_keys=True).encode()).hexdigest()


def make_chunks(messages: list[Message], max_chars: int = 220, max_messages: int = 3) -> list[Chunk]:
    """Group neighbouring turns; split long text with exact character offsets."""
    chunks: list[Chunk] = []
    parts: list[str] = []
    spans: list[dict] = []
    conversation_id = ""

    def flush():
        if spans:
            chunks.append(Chunk("\n".join(parts), conversation_id, spans.copy()))
            parts.clear()
            spans.clear()

    for message in messages:
        if message.conversation_id != conversation_id:
            flush()
            conversation_id = message.conversation_id
        if message.message_type != "message" or not message.text.strip():
            flush()
            continue
        if re.fullmatch(r"\s*<[^>]*(?:omitted|attached)[^>]*>\s*", message.text, re.IGNORECASE):
            flush()
            continue
        # Keep each model input short, including the speaker label.
        label = (message.speaker or "Unknown")[:80] + ": "
        segment_size = max_chars - len(label)
        for start in range(0, len(message.text), segment_size):
            segment = message.text[start:start + segment_size]
            part = label + segment
            if spans and (len(spans) >= max_messages or len("\n".join(parts + [part])) > max_chars):
                flush()
            parts.append(part)
            spans.append({"message_id": message.id, "start_char": start, "end_char": start + len(segment)})
    flush()
    return chunks


def source_fingerprint(session, profile_id: str) -> str:
    records = session.execute(select(Conversation.id, Conversation.source_hash).where(
        Conversation.profile_id == profile_id,
    ).order_by(Conversation.id)).all()
    return sha256(json.dumps(["chunks-v1", [list(row) for row in records]]).encode()).hexdigest()


class RetrievalService:
    batch_size = 32

    def __init__(self, database: Database, embedder: EmbeddingProvider | None = None):
        self.database = database
        self.path = Path(database.engine.url.database).parent
        self.embedder = embedder or LocalEmbeddings(self.path / "models/all-MiniLM-L6-v2")
        self.build_lock = Lock()

    @cached_property
    def client(self):
        import chromadb
        from chromadb.config import Settings

        return chromadb.PersistentClient(
            path=str(self.path / "chroma"), settings=Settings(anonymized_telemetry=False),
        )

    def vectors(self, texts: list[str]) -> list[list[float]]:
        vectors = self.embedder.embed(texts)
        if len(vectors) != len(texts) or not vectors:
            raise ValueError("Embedding provider returned an invalid number of vectors")
        size = len(vectors[0])
        if not size or any(len(v) != size or not all(math.isfinite(x) for x in v) or not any(v) for v in vectors):
            raise ValueError("Embedding provider returned invalid vectors")
        return vectors

    def build(self, profile_id: str) -> dict:
        """Publish only after every vector is stored; keep the previous snapshot on failure."""
        with self.build_lock:
            with self.database.sessions() as session:
                fingerprint = source_fingerprint(session, profile_id)
                messages = list(session.scalars(select(Message).join(Conversation).where(
                    Conversation.profile_id == profile_id,
                ).order_by(Conversation.id, Message.sequence_number)))
                chunks = make_chunks(messages)
            name = "echo-" + uuid4().hex
            created = False
            try:
                collection = self.client.create_collection(
                    name, embedding_function=None, configuration={"hnsw": {"space": "cosine"}},
                )
                created = True
                for start in range(0, len(chunks), self.batch_size):
                    batch = chunks[start:start + self.batch_size]
                    vectors = self.vectors([chunk.text for chunk in batch])
                    collection.add(
                        ids=[chunk.id for chunk in batch],
                        embeddings=vectors, documents=[chunk.text for chunk in batch],
                        metadatas=[{
                            "profile_id": profile_id, "conversation_id": chunk.conversation_id,
                            "spans": json.dumps(chunk.spans),
                        } for chunk in batch],
                    )
                with self.database.sessions.begin() as session:
                    if source_fingerprint(session, profile_id) != fingerprint:
                        raise IndexRequired("Imports changed during indexing. Build the index again.")
                    index = session.get(SemanticIndex, profile_id)
                    if index is None:
                        index = SemanticIndex(profile_id=profile_id)
                        session.add(index)
                    index.collection_name = name
                    index.fingerprint = fingerprint
                    index.model = self.embedder.model
                    index.chunk_count = len(chunks)
                return {"profile_id": profile_id, "chunks": len(chunks), "model": self.embedder.model}
            except Exception as error:
                if created:
                    try:
                        self.client.delete_collection(name)
                    except Exception:
                        pass  # A failed cache cleanup must not hide the original error.
                if isinstance(error, IndexRequired):
                    raise
                logger.exception("Semantic index build failed for profile %s", profile_id)
                raise RetrievalUnavailable("Indexing failed; source messages and the previous index are unchanged.") from error

    def search(self, profile_id: str, query: str, limit: int, min_score: float) -> dict:
        with self.database.sessions() as session:
            index = session.get(SemanticIndex, profile_id)
            if index is None or index.fingerprint != source_fingerprint(session, profile_id) or index.model != self.embedder.model:
                raise IndexRequired("Build this profile's index before searching; it is missing or out of date.")
            if not index.chunk_count:
                return {"items": [], "model": index.model}
            try:
                collection = self.client.get_collection(index.collection_name, embedding_function=None)
                result = collection.query(
                    query_embeddings=self.vectors([query]), n_results=min(limit, index.chunk_count),
                    where={"profile_id": profile_id}, include=["documents", "metadatas", "distances"],
                )
                items = []
                for chunk_id, text, metadata, distance in zip(
                    result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0], strict=True,
                ):
                    score = max(0.0, min(1.0, 1.0 - distance))
                    if score < min_score:
                        continue
                    spans = json.loads(metadata["spans"])
                    ids = list(dict.fromkeys(span["message_id"] for span in spans))
                    messages = list(session.scalars(select(Message).join(Conversation).where(
                        Conversation.profile_id == profile_id,
                        Message.conversation_id == metadata["conversation_id"], Message.id.in_(ids),
                    ).order_by(Message.sequence_number)))
                    if len(messages) != len(ids):
                        raise IndexRequired("Source records changed. Rebuild the index.")
                    items.append({
                        "chunk_id": chunk_id, "conversation_id": metadata["conversation_id"],
                        "text": text, "score": score, "spans": spans, "messages": messages,
                    })
                return {"items": items, "model": index.model}
            except IndexRequired:
                raise
            except Exception as error:
                logger.exception("Semantic query failed for profile %s", profile_id)
                raise RetrievalUnavailable("Semantic search is unavailable. Check the model cache and rebuild the index.") from error
