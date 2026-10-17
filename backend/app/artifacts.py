"""Deterministic extractive summaries and explicitly uncertain reference candidates."""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256

from app.database import Message


METHOD = "extractive-rules-v1"
SEGMENT_SIZE = 20
STOPWORDS = set("""
a an the and or but if in on at to for from of with by is are was were be been
being i me my we us our you your he him his she her it its they them their this
that these those there here have has had do does did can could will would shall
should may might must not no yes so as also just very really about what when
where how why who which lets let today tomorrow yesterday tonight then now
please thanks thank okay ok hi hello going get got want need like think know
say said see come good time before after together start let's
""".split())
EVENT_WORDS = re.compile(r"\b(?:meet(?:ing)?|appointment|birthday|wedding|exam|flight|trip|conference|interview|deadline)\b", re.IGNORECASE)


@dataclass
class Candidate:
    kind: str
    key: str
    content: str
    source_ids: list[str]
    uncertain: bool


def usable(message: Message) -> bool:
    return bool(message.message_type == "message" and message.text.strip() and not re.fullmatch(
        r"\s*<[^>]*(?:omitted|attached)[^>]*>\s*", message.text, re.IGNORECASE,
    ))


def tokens(text: str) -> list[str]:
    return [word for word in re.findall(r"[^\W\d_]{3,}", text.casefold()) if word not in STOPWORDS]


def excerpt(message: Message, start: int = 0) -> str:
    # Quoted extracts stay exact; an explicit marker indicates omitted trailing text.
    text = message.text[start:start + 500]
    prefix = "[excerpt starts later] " if start else ""
    suffix = " [excerpt continues]" if len(message.text) > start + 500 else ""
    return f"{message.speaker}: {prefix}{text}{suffix}"


def candidates(messages: list[Message]) -> list[Candidate]:
    output: list[Candidate] = []
    for start in range(0, len(messages), SEGMENT_SIZE):
        segment = messages[start:start + SEGMENT_SIZE]
        eligible = [message for message in segment if usable(message)]
        if not eligible:
            continue
        frequencies = Counter(word for message in eligible for word in set(tokens(message.text)))
        # Prefer informative, recurring vocabulary. Break ties by original order.
        ranked = sorted(eligible, key=lambda message: (
            -sum(frequencies[word] for word in set(tokens(message.text))), message.sequence_number,
        ))
        selected, seen = [], set()
        for message in ranked:
            if message.text in seen:
                continue
            selected.append(message)
            seen.add(message.text)
            if len(selected) == 3:
                break
        selected.sort(key=lambda message: message.sequence_number)
        output.append(Candidate(
            "summary", f"segment-{start // SEGMENT_SIZE + 1}",
            "\n".join(excerpt(message) for message in selected),
            [message.id for message in selected], False,
        ))

    speakers: dict[str, list[str]] = defaultdict(list)
    terms: dict[str, list[str]] = defaultdict(list)
    for message in messages:
        if message.message_type == "message" and message.speaker:
            speakers[message.speaker].append(message.id)
        if not usable(message):
            continue
        for word in set(tokens(message.text)):
            terms[word].append(message.id)
        event = EVENT_WORDS.search(message.text)
        if event:
            output.append(Candidate("event", message.id, excerpt(message, max(0, event.start() - 100)), [message.id], True))
    for speaker, ids in sorted(speakers.items()):
        key = sha256(speaker.encode()).hexdigest()
        output.append(Candidate("person", key, f"Participant label: {speaker}", ids, True))
    for term in sorted(terms, key=lambda word: (-len(terms[word]), word))[:5]:
        output.append(Candidate("topic", term, term, terms[term], True))
    return output
