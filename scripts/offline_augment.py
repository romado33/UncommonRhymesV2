from __future__ import annotations
from llm.providers import complete_json

def normalize_artist(row: dict) -> dict:
    js = complete_json(
        f"Normalize artist name and add era for: {row}",
        schema_hint="{'artist':str,'era':str}",
        temperature=0.1,
    )
    if isinstance(js, dict):
        row.update({k: v for k, v in js.items() if k in ("artist","era")})
    return row

if __name__ == "__main__":
    pass