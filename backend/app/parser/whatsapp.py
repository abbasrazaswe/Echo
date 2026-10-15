"""Parse common WhatsApp text exports without guessing date order."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


DateOrder = Literal["day-first", "month-first"]
DATE = r"\d{1,2}[/.\-]\d{1,2}[/.\-](?:\d{4}|\d{2})"
TIME = r"\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?"
HEADER = re.compile(
    rf"^(?:\[(?P<ios_date>{DATE}),?\s+(?P<ios_time>{TIME})\]\s*"
    rf"|(?P<android_date>{DATE}),?\s+(?P<android_time>{TIME})\s+-\s+)"
    r"(?P<body>.*)$"
)
HEADER_LIKE = re.compile(r"^\[?\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}(?:,|\s)")


class ParseError(ValueError):
    """A transcript cannot be parsed safely."""


class MessageRecord(BaseModel):
    sequence_number: int = Field(ge=1)
    speaker: str | None
    text: str
    timestamp: datetime
    raw_timestamp: str
    message_type: Literal["message", "system"]
    source_type: Literal["whatsapp_export"] = "whatsapp_export"
    source_line_start: int = Field(ge=1)
    source_line_end: int = Field(ge=1)
    raw_record: str


def parse_timestamp(date: str, time: str, date_order: DateOrder) -> datetime:
    date_parts = re.split(r"[/.\-]", date)
    year_format = "%Y" if len(date_parts[2]) == 4 else "%y"
    date_format = "%d/%m/" if date_order == "day-first" else "%m/%d/"
    time = re.sub(r"\s*([AaPp][Mm])$", r" \1", time).upper()
    has_seconds = time.count(":") == 2
    time_format = "%I:%M" if time.endswith(("AM", "PM")) else "%H:%M"
    if has_seconds:
        time_format += ":%S"
    if time.endswith(("AM", "PM")):
        time_format += " %p"
    return datetime.strptime(
        "/".join(date_parts) + " " + time,
        date_format + year_format + " " + time_format,
    )


def parse_whatsapp(text: str, *, date_order: DateOrder) -> list[MessageRecord]:
    """Preserve export order, multiline content, and source text.

    Timestamps are local times without a timezone: exports do not supply one.
    Header-shaped content inside a message is inherently ambiguous in this format.
    """
    if date_order not in ("day-first", "month-first"):
        raise ParseError("Choose day-first or month-first date order.")
    records: list[MessageRecord] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        # Ignore export formatting markers for matching, but retain the raw line.
        line = raw_line.lstrip("\ufeff\u200e\u200f").replace("\u202f", " ").replace("\u00a0", " ")
        header = HEADER.match(line)
        if header:
            date = header["ios_date"] or header["android_date"]
            time = header["ios_time"] or header["android_time"]
            try:
                timestamp = parse_timestamp(date, time, date_order)
            except ValueError as error:
                raise ParseError(f"Invalid timestamp on line {line_number}; check the date order.") from error
            # Read the original body so Unicode spacing and markers survive.
            body = raw_line[len(raw_line) - len(header["body"]):] if header["body"] else ""
            speaker, separator, content = body.partition(": ")
            is_message = bool(separator and speaker.strip())
            records.append(MessageRecord(
                sequence_number=len(records) + 1,
                speaker=speaker if is_message else None,
                text=content if is_message else body,
                timestamp=timestamp,
                raw_timestamp=f"{date}, {time}",
                message_type="message" if is_message else "system",
                source_line_start=line_number,
                source_line_end=line_number,
                raw_record=raw_line,
            ))
        elif HEADER_LIKE.match(line):
            raise ParseError(f"Unsupported or malformed message header on line {line_number}.")
        elif records:
            records[-1].text += "\n" + raw_line
            records[-1].raw_record += "\n" + raw_line
            records[-1].source_line_end = line_number
        elif raw_line.strip("\ufeff\u200e\u200f \t"):
            raise ParseError(f"Unrecognized content before the first message on line {line_number}.")
    if not records:
        raise ParseError("No timestamped messages found in the transcript.")
    return records
