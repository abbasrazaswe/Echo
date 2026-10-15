"""Run with: python -m app.parser INPUT --date-order day-first --output OUTPUT."""

import argparse
import json
from pathlib import Path

from app.parser.whatsapp import ParseError, parse_whatsapp


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a WhatsApp UTF-8 text export to JSON.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--date-order", choices=["day-first", "month-first"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("The output must be different from the input file.")
    try:
        records = parse_whatsapp(args.input.read_text(encoding="utf-8-sig"), date_order=args.date_order)
        payload = json.dumps([record.model_dump(mode="json") for record in records], ensure_ascii=False, indent=2)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(payload + "\n")
    except (OSError, UnicodeError, ParseError) as error:
        parser.error(str(error))
    print(f"Exported {len(records)} records to {args.output}")


if __name__ == "__main__":
    main()
