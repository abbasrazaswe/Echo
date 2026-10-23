"""Explicit speaker labels delimit undated messages; no dates are inferred."""
from app.parser.whatsapp import MessageRecord, ParseError


def parse_labelled(text: str, *, speakers: list[str]) -> list[MessageRecord]:
    labels = {speaker.strip() for speaker in speakers}
    if not labels or len(labels) > 50 or any(not label or len(label) > 200 or '\n' in label or '\r' in label or ':' in label for label in labels):
        raise ParseError('Supply participant labels without colons, one per line (up to 200 characters each).')
    records: list[MessageRecord] = []
    lines: list[str] = []
    speaker = None
    start = 0

    def finish(end: int):
        if speaker is None:
            return
        content = '\n'.join(lines[1:])
        records.append(MessageRecord(
            sequence_number=len(records) + 1, speaker=speaker, text=content,
            timestamp=None, raw_timestamp=None, message_type='message',
            source_type='speaker_labelled', source_line_start=start,
            source_line_end=end, raw_record='\n'.join(lines),
        ))

    for number, raw in enumerate(text.splitlines(), 1):
        label = raw.lstrip('\ufeff\u200e\u200f').strip()
        if label.endswith(':') and label[:-1] in labels:
            finish(number - 1)
            speaker, start, lines = label[:-1], number, [raw]
        elif speaker is not None:
            lines.append(raw)
        elif raw.strip('\ufeff\u200e\u200f \t'):
            raise ParseError(f'Expected a configured participant label followed by a colon on line {number}.')
    finish(start + len(lines) - 1)
    if not records:
        raise ParseError('No configured participant labels found in the transcript.')
    if labels - {row.speaker for row in records}:
        raise ParseError('One or more participant labels were not found; check their exact spelling.')
    return records
