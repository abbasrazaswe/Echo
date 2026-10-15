import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.parser.whatsapp import ParseError, parse_whatsapp


BACKEND = Path(__file__).resolve().parents[1]
SAMPLE = BACKEND / "tests/fixtures/whatsapp_sample.txt"


def test_sample_preserves_order_multiline_system_and_media():
    records = parse_whatsapp(SAMPLE.read_text(), date_order="day-first")
    assert [record.sequence_number for record in records] == [1, 2, 3, 4]
    assert [record.speaker for record in records] == [None, "Ali", "Sara", "Ali"]
    assert records[0].message_type == "system"
    assert records[2].text == "Yes! Let's start with functions.\nThen we can try a small project 🙂"
    assert (records[2].source_line_start, records[2].source_line_end) == (3, 4)
    assert records[3].text == "<Media omitted>"
    assert records[1].timestamp.isoformat() == "2026-10-14T09:01:00"
    assert "\n".join(record.raw_record for record in records) == SAMPLE.read_text().rstrip("\n")


@pytest.mark.parametrize("header, expected", [
    ("[14/10/2026, 9:02:03 PM]", "2026-10-14T21:02:03"),
    ("14/10/26, 12:00 AM -", "2026-10-14T00:00:00"),
    ("14/10/26, 12:00 PM -", "2026-10-14T12:00:00"),
    ("14.10.2026, 09:02 -", "2026-10-14T09:02:00"),
    ("14-10-2026, 09:02 -", "2026-10-14T09:02:00"),
    ("\ufeff\u200e[14/10/2026, 9:02\u202fpm]", "2026-10-14T21:02:00"),
])
def test_header_variants(header, expected):
    record = parse_whatsapp(header + " Sara: Hello", date_order="day-first")[0]
    assert record.timestamp.isoformat() == expected
    assert record.text == "Hello"


def test_date_order_is_explicit():
    text = "04/05/2026, 09:00 - Ali: Hello"
    assert parse_whatsapp(text, date_order="day-first")[0].timestamp.month == 5
    assert parse_whatsapp(text, date_order="month-first")[0].timestamp.month == 4


def test_preserves_unicode_colons_blank_lines_and_original_order():
    text = "[14/10/2026, 09:02] Sara: سلام\u00a0🙂: hello\n\nsecond line\n[14/10/2026, 09:01] Ali: Earlier timestamp"
    records = parse_whatsapp(text, date_order="day-first")
    assert records[0].text == "سلام\u00a0🙂: hello\n\nsecond line"
    assert records[0].timestamp > records[1].timestamp
    assert records[0].raw_record == text.split("\n[14/10/2026, 09:01]")[0]


@pytest.mark.parametrize("text", [
    "", "random text", "\n\n", "31/02/2026, 09:00 - Ali: Hello",
    "14/10/2026, 25:00 - Ali: Hello",
    "14/10/2026, 09:00 - Ali: Hello\n14/10/2026, invalid - Sara: Lost message",
])
def test_unreadable_content_fails_instead_of_dropping_it(text):
    with pytest.raises(ParseError):
        parse_whatsapp(text, date_order="day-first")


def test_crlf_and_blank_leading_lines():
    records = parse_whatsapp("\r\n14/10/2026, 09:00 - Ali: Hello\r\ncontinued\r\n", date_order="day-first")
    assert records[0].text == "Hello\ncontinued"
    assert records[0].source_line_start == 2


def run_cli(source, output):
    return subprocess.run(
        [sys.executable, "-m", "app.parser", str(source), "--date-order", "day-first", "--output", str(output)],
        cwd=BACKEND, capture_output=True, text=True,
    )


def test_cli_exports_valid_json_and_refuses_overwrite(tmp_path):
    output = tmp_path / "records.json"
    result = run_cli(SAMPLE, output)
    assert result.returncode == 0, result.stderr
    records = json.loads(output.read_text())
    assert len(records) == 4
    assert records[2]["speaker"] == "Sara"
    saved = output.read_bytes()
    assert run_cli(SAMPLE, output).returncode != 0
    assert output.read_bytes() == saved


def test_cli_leaves_no_output_for_invalid_input(tmp_path):
    source = tmp_path / "invalid.txt"
    source.write_text("This is not an export")
    output = tmp_path / "records.json"
    assert run_cli(source, output).returncode != 0
    assert not output.exists()


def test_cli_rejects_same_source_and_output(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(SAMPLE.read_bytes())
    saved = source.read_bytes()
    assert run_cli(source, source).returncode != 0
    assert source.read_bytes() == saved
