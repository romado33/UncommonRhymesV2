"""Command-line entrypoint for UncommonRhymesV2 searches."""
from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from config import FLAGS
from rhyme_core.search import search_word

logging.basicConfig(level=getattr(logging, str(FLAGS.get("LOG_LEVEL", "INFO")).upper(), logging.INFO))


def _row_to_dict(row: Any) -> dict:
    if isinstance(row, dict):
        return row
    return dict(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search for rhymes using UncommonRhymesV2")
    parser.add_argument("word", help="Query word to rhyme with")
    parser.add_argument("--top", type=int, default=int(FLAGS.get("TOP_K", 100)), help="Number of results to show")
    parser.add_argument("--include-consonant", action="store_true", help="Show consonant rhymes even if disabled via env")
    parser.add_argument("--json", action="store_true", help="Emit results as JSON")
    args = parser.parse_args()

    rows = search_word(
        args.word,
        max_results=args.top,
        include_consonant=args.include_consonant,
    )
    rows = rows[: args.top]
    if args.json:
        print(json.dumps([_row_to_dict(r) for r in rows], indent=2))
    else:
        for row in rows:
            data = _row_to_dict(row)
            print(f"{data.get('word'):<20} {data.get('rhyme_type'):<10} score={data.get('score'):.3f}")


if __name__ == "__main__":
    main()
