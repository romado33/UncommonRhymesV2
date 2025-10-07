---
title: Uncommon Rhymes V2
emoji: 🪄
colorFrom: green
colorTo: blue
sdk: gradio
sdk_version: "4.44.1"
app_file: app.py
pinned: false
---

# Uncommon Rhymes V2

Fast rhyme search (CMU dict, indexed) with explainable rhyme types, rarity scoring, and a Patterns tab (optional DB).

## Quickstart

```bash
pip install -r requirements.txt
pytest -q
python cli.py hat --top 50
gradio app.py
```

## Design

Uncommon Rhymes V2 anchors on CMUdict pronunciations. We classify rhyme pairs
into **perfect**, **slant**, **assonance**, and **consonance** buckets by
comparing stressed vowels and codas. Candidate scores blend rhyme quality with a
light rarity boost so interesting words float to the top without overwhelming
the list. The UI enables toggling rhyme types, with consonance disabled by
default to keep the "uncommon" feed focused on stronger matches. Optional
filters (syllable bounds, rarity floor, patterns DB lookup) refine the final
display.

## Contributing

External contributors only have read access to the upstream Hugging Face repo, so
the "Create PR" button will fail with **Branch creation unauthorized**. To submit
changes:

1. Fork the project to your own GitHub account.
2. Push a feature branch to your fork.
3. Open a pull request from `<your fork>/<branch>` back to `UncommonRhymesV2`.

Running `pytest` locally before opening the PR will exercise the deterministic
fallback dataset that ships with the repo, so you can iterate without the large
SQLite index.
