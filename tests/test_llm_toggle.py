"""Tests for optional LLM toggles."""
from __future__ import annotations

import importlib

import pytest


def _reload(monkeypatch: pytest.MonkeyPatch, **env: str):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import config
    import rhyme_core.search as search

    importlib.reload(config)
    importlib.reload(search)
    return search


def test_llm_disabled(monkeypatch: pytest.MonkeyPatch):
    search = _reload(monkeypatch, USE_LLM="0")
    rows = search.search_word("hat", max_results=5)
    assert rows and all("word" in r for r in rows)


def test_llm_enabled_no_provider(monkeypatch: pytest.MonkeyPatch):
    base = _reload(monkeypatch, USE_LLM="0").search_word("hat", max_results=5)
    search = _reload(monkeypatch, USE_LLM="1", LLM_PROVIDER="nonexistent")
    rows = search.search_word("hat", max_results=5)
    assert rows == base
