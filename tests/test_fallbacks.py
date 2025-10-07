"""Fallback behaviour tests."""
from __future__ import annotations

import importlib
from typing import Iterable

import pytest


def _reload_search(monkeypatch: pytest.MonkeyPatch, env: Iterable[tuple[str, str]] = ()):
    for key, value in env:
        monkeypatch.setenv(key, value)
    import config
    import rhyme_core.search as search

    importlib.reload(config)
    importlib.reload(search)
    return search


def test_basic_rhyme(monkeypatch: pytest.MonkeyPatch):
    search = _reload_search(monkeypatch)
    rows = search.search_word("hat", max_results=10)
    assert any(r["word"] == "cat" for r in rows)


def test_consonance_hidden_by_default(monkeypatch: pytest.MonkeyPatch):
    search = _reload_search(monkeypatch)
    rows = search.search_word("double", max_results=10)
    assert all(r.get("rhyme_type") != "consonant" for r in rows)


def test_symmetry_like_pair(monkeypatch: pytest.MonkeyPatch):
    search = _reload_search(monkeypatch)
    time_rows = search.search_word("time", max_results=10)
    rhyme_rows = search.search_word("rhyme", max_results=10)
    assert any(r["word"] == "rhyme" for r in time_rows)
    assert any(r["word"] == "time" for r in rhyme_rows)


def test_fallback_normalizes_punctuation(monkeypatch: pytest.MonkeyPatch):
    search = _reload_search(monkeypatch)
    rows = search.search_word("hat!!!", max_results=10)
    assert any(r["word"] == "cat" for r in rows)
