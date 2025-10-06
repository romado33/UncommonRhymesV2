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
