"""Measured writing patterns and reviewed presentation settings, never factual evidence."""

import json
import re
from collections import Counter, defaultdict
from hashlib import sha256
from statistics import mean, median
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.api import SessionDependency, require_conversation, require_profile
from app.artifacts import STOPWORDS, usable
from app.database import Conversation, Message, ProfileStyle


router = APIRouter(prefix="/profiles/{profile_id}/style", tags=["Conversational style"])
METHOD = "writing-patterns-v1"
EMOJI = re.compile("[\U0001f1e6-\U0001f1ff\U0001f300-\U0001faff\u2600-\u27bf]")
LATIN = re.compile(r"[A-Za-z]")
ARABIC_SCRIPT = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")
Word = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]


class StyleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    length: Literal["brief", "balanced", "detailed"] = "balanced"
    tone: Literal["neutral", "casual", "warm", "formal"] = "neutral"
    punctuation: Literal["standard", "light", "expressive"] = "standard"
    emoji_usage: Literal["none", "occasional"] = "none"
    capitalization: Literal["standard", "mostly_lowercase"] = "standard"
    language: Literal["match_user", "english", "urdu", "roman_urdu", "english_urdu_mix"] = "match_user"
    preferred_words: list[Word] = Field(default_factory=list, max_length=10)

    @field_validator("preferred_words")
    @classmethod
    def single_words(cls, words):
        if any(not re.fullmatch(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", word) for word in words):
            raise ValueError("Preferred words must be individual words, not sentences or instructions.")
        return list(dict.fromkeys(words))


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    length: Literal["brief", "balanced", "detailed"] | None = None
    tone: Literal["neutral", "casual", "warm", "formal"] | None = None
    punctuation: Literal["standard", "light", "expressive"] | None = None
    emoji_usage: Literal["none", "occasional"] | None = None
    capitalization: Literal["standard", "mostly_lowercase"] | None = None
    language: Literal["match_user", "english", "urdu", "roman_urdu", "english_urdu_mix"] | None = None
    preferred_words: list[Word] | None = Field(default=None, max_length=10)

    @field_validator("preferred_words")
    @classmethod
    def single_words(cls, words):
        return StyleSettings.single_words(words) if words is not None else None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Provide at least one non-null style setting.")
        return self


class StyleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    settings: SettingsPatch


class AnalyzeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    revision: int = Field(ge=0)
    speaker: str = Field(min_length=1, max_length=200)
    conversation_id: str | None = Field(default=None, min_length=1)


class StyleOutput(BaseModel):
    profile_id: str
    revision: int
    speaker: str | None
    conversation_id: str | None
    analysis: dict | None
    suggested_settings: StyleSettings | None
    settings: StyleSettings
    analysis_stale: bool


class AppliedStyle(BaseModel):
    revision: int
    settings: StyleSettings


def fingerprint(session, profile_id, speaker, conversation_id):
    query = select(Conversation.id, Conversation.source_hash).where(Conversation.profile_id == profile_id)
    if conversation_id:
        query = query.where(Conversation.id == conversation_id)
    rows = [list(row) for row in session.execute(query.order_by(Conversation.id))]
    return sha256(json.dumps([METHOD, speaker, rows]).encode()).hexdigest()


def measurements(texts: list[str]) -> dict:
    word_counts = [len(re.findall(r"\S+", text)) for text in texts]
    cased = [text for text in texts if any(char.islower() or char.isupper() for char in text)]
    arabic = [any(match.group().isalpha() for match in ARABIC_SCRIPT.finditer(text)) for text in texts]
    latin = [bool(LATIN.search(text)) for text in texts]
    mixed = sum(left and right for left, right in zip(latin, arabic, strict=True))
    count = len(texts)
    return {
        "message_count": count,
        "mean_words": round(mean(word_counts), 2) if count else 0,
        "median_words": median(word_counts) if count else 0,
        "mean_characters": round(mean(map(len, texts)), 2) if count else 0,
        "terminal_punctuation_rate": sum(bool(re.search(r"[.!?؟。！？]$", text.rstrip())) for text in texts) / count if count else 0,
        "emoji_message_rate": sum(bool(EMOJI.search(text)) for text in texts) / count if count else 0,
        "approximate_emoji_codepoints": sum(len(EMOJI.findall(text)) for text in texts),
        "lowercase_message_rate": sum(text == text.lower() for text in cased) / len(cased) if cased else None,
        "script_messages": {
            "latin_only": sum(left and not right for left, right in zip(latin, arabic, strict=True)),
            "arabic_script_only": sum(right and not left for left, right in zip(latin, arabic, strict=True)),
            "mixed_latin_arabic": mixed,
            "neither": sum(not left and not right for left, right in zip(latin, arabic, strict=True)),
        },
        "mixed_script_rate": mixed / count if count else 0,
    }


def analyze(messages: list[Message], more_records: bool) -> tuple[dict, dict]:
    texts, source_ids = [], []
    words, phrases, emoji = Counter(), Counter(), Counter()
    phrase_sources = defaultdict(list)
    remaining = 100_000
    clipped = 0
    for message in messages:
        if not usable(message):
            continue
        if not remaining:
            break
        text = message.text[:min(1000, remaining)]
        clipped += len(text) < len(message.text)
        remaining -= len(text)
        texts.append(text)
        source_ids.append(message.id)
        tokens = re.findall(r"[^\W\d_]{2,}", text.casefold())
        words.update(word for word in tokens if word not in STOPWORDS and len(word) <= 32)
        emoji.update(EMOJI.findall(text))
        seen = set()
        for size in (2, 3):
            for start in range(len(tokens) - size + 1):
                part = tokens[start:start + size]
                phrase = " ".join(part)
                if len(phrase) <= 60 and any(word not in STOPWORDS for word in part):
                    seen.add(phrase)
        for phrase in seen:
            phrases[phrase] += 1
            if len(phrase_sources[phrase]) < 3:
                phrase_sources[phrase].append(message.id)
    if not texts:
        raise HTTPException(422, "No usable messages for this speaker in the selected scope")
    stats = measurements(texts)
    common = sorted(words.items(), key=lambda item: (-item[1], item[0]))[:10]
    repeated = sorted((item for item in phrases.items() if item[1] >= 2), key=lambda item: (-item[1], item[0]))[:10]
    suggestions = StyleSettings(
        length="brief" if stats["median_words"] <= 10 else "detailed" if stats["median_words"] >= 30 else "balanced",
        punctuation="light" if stats["terminal_punctuation_rate"] < 0.3 else "standard",
        emoji_usage="occasional" if stats["emoji_message_rate"] >= 0.1 else "none",
        capitalization="mostly_lowercase" if stats["message_count"] >= 5 and (stats["lowercase_message_rate"] or 0) >= 0.75 else "standard",
        preferred_words=[word for word, count in common if count >= 2],
    )
    return {
        "method": METHOD, "metrics": stats, "source_message_ids": source_ids,
        "sample_limited": len(texts) < 20,
        "sample_truncated": more_records or bool(clipped) or len(source_ids) < sum(usable(message) for message in messages),
        "sampled_characters": 100_000 - remaining,
        "common_words": [{"word": word, "occurrences": count} for word, count in common],
        "common_phrases": [{"phrase": phrase, "message_count": count, "source_message_ids": phrase_sources[phrase]} for phrase, count in repeated],
        "common_emojis": [{"symbol": symbol, "approximate_codepoints": count} for symbol, count in sorted(emoji.items(), key=lambda item: (-item[1], item[0]))[:10]],
    }, suggestions.model_dump()


def view(session, profile_id: str) -> dict:
    record = session.get(ProfileStyle, profile_id)
    return {
        "profile_id": profile_id, "revision": record.revision if record else 0,
        "speaker": record.speaker if record else None,
        "conversation_id": record.conversation_id if record else None,
        "analysis": record.analysis if record else None,
        "suggested_settings": record.suggested_settings if record else None,
        "settings": record.settings if record else StyleSettings().model_dump(),
        "analysis_stale": bool(record and record.fingerprint and record.fingerprint != fingerprint(session, profile_id, record.speaker, record.conversation_id)),
    }


def save(session, profile_id, revision, values):
    current = session.get(ProfileStyle, profile_id)
    if (current.revision if current else 0) != revision:
        raise HTTPException(409, "Style changed. Reload its revision before updating.")
    try:
        if current:
            changed = session.execute(update(ProfileStyle).where(
                ProfileStyle.profile_id == profile_id, ProfileStyle.revision == revision,
            ).values(**values, revision=revision + 1))
            if not changed.rowcount:
                raise HTTPException(409, "Style changed. Reload before updating.")
        else:
            session.add(ProfileStyle(profile_id=profile_id, revision=1,
                **{"settings": StyleSettings().model_dump(), **values}))
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "Style changed. Reload before updating.") from error


@router.get("", response_model=StyleOutput)
def get_style(profile_id: str, session: SessionDependency):
    require_profile(session, profile_id)
    return view(session, profile_id)


@router.post("/analyze", response_model=StyleOutput)
def analyze_style(profile_id: str, body: AnalyzeInput, session: SessionDependency):
    require_profile(session, profile_id)
    if body.conversation_id:
        require_conversation(session, profile_id, body.conversation_id)
    source_signature = fingerprint(session, profile_id, body.speaker, body.conversation_id)
    query = select(Message).join(Conversation).where(
        Conversation.profile_id == profile_id, Message.speaker == body.speaker,
    )
    if body.conversation_id:
        query = query.where(Message.conversation_id == body.conversation_id)
    messages = list(session.scalars(query.order_by(Conversation.started_at, Conversation.id, Message.sequence_number).limit(1001)))
    analysis, suggestions = analyze(messages[:1000], len(messages) > 1000)
    save(session, profile_id, body.revision, {
        "speaker": body.speaker, "conversation_id": body.conversation_id,
        "analysis": analysis, "suggested_settings": suggestions,
        "fingerprint": source_signature,
    })
    return view(session, profile_id)


@router.patch("", response_model=StyleOutput)
def update_style(profile_id: str, body: StyleUpdate, session: SessionDependency):
    require_profile(session, profile_id)
    current = session.get(ProfileStyle, profile_id)
    settings = StyleSettings.model_validate({
        **(current.settings if current else StyleSettings().model_dump()),
        **body.settings.model_dump(exclude_unset=True),
    })
    save(session, profile_id, body.revision, {"settings": settings.model_dump()})
    return view(session, profile_id)


class EvaluateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=4000)


@router.post("/evaluate")
def evaluate_style(profile_id: str, body: EvaluateInput, session: SessionDependency):
    require_profile(session, profile_id)
    current = view(session, profile_id)
    settings = StyleSettings.model_validate(current["settings"])
    observed = measurements([body.text])
    word_count = observed["median_words"]
    length_check = word_count <= 40 if settings.length == "brief" else word_count <= 120 if settings.length == "balanced" else word_count >= 40
    return {
        "revision": current["revision"], "enabled": settings.enabled,
        "observed": observed, "source_baseline": current["analysis"]["metrics"] if current["analysis"] else None,
        "analysis_stale": current["analysis_stale"],
        "checks": {"length_band": length_check,
                   "emoji_budget": observed["approximate_emoji_codepoints"] <= (2 if settings.emoji_usage == "occasional" else 0),
                   "capitalization": settings.capitalization != "mostly_lowercase" or observed["lowercase_message_rate"] in (None, 1)},
        "preferred_words_present": [word for word in settings.preferred_words if word.casefold() in re.findall(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", body.text.casefold())],
        "not_evaluated": ["tone", "language_identity", "semantic_similarity", "factual_grounding"],
    }


def applied_style(session, profile_id: str) -> dict | None:
    record = session.get(ProfileStyle, profile_id)
    if not record:
        return None
    settings = StyleSettings.model_validate(record.settings)
    return AppliedStyle(revision=record.revision, settings=settings).model_dump() if settings.enabled else None
