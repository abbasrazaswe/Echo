"""Run with: python -m app.parser INPUT --date-order day-first --output OUTPUT."""

import argparse
import json
from pathlib import Path

from app.parser.labelled import parse_labelled
from app.parser.whatsapp import ParseError, parse_whatsapp


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert dated WhatsApp or explicit undated speaker-labelled UTF-8 text to JSON.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--date-order", choices=["day-first", "month-first"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", choices=["whatsapp", "speaker-labelled"], default="whatsapp")
    parser.add_argument("--speaker", action="append", default=[])
    args = parser.parse_args()
    if args.format == "whatsapp" and (not args.date_order or args.speaker):
        parser.error("WhatsApp requires --date-order and no --speaker arguments.")
    if args.format == "speaker-labelled" and (args.date_order or not args.speaker):
        parser.error("Undated text requires --speaker arguments and no --date-order.")
    if args.input.resolve() == args.output.resolve():
        parser.error("The output must be different from the input file.")
    try:
        text = args.input.read_text(encoding="utf-8-sig")
        records = (parse_labelled(text, speakers=args.speaker) if args.format == "speaker-labelled"
                   else parse_whatsapp(text, date_order=args.date_order))
        payload = json.dumps([record.model_dump(mode="json") for record in records], ensure_ascii=False, indent=2)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(payload + "\n")
    except (OSError, UnicodeError, ParseError) as error:
        parser.error(str(error))
    print(f"Exported {len(records)} records to {args.output}")


if __name__ == "__main__":
    main()
