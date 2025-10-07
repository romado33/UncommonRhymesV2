"""Utility helpers for lazily accessing optional LLM providers."""
from __future__ import annotations

from config import FLAGS


def get_llm():
    """Return a provider wrapper if LLM access is enabled and available."""
    if not FLAGS.get("USE_LLM"):
        return None
    try:
        from .providers import get_provider
    except Exception:
        return None
    provider_name = FLAGS.get("LLM_PROVIDER", "")
    return get_provider(provider_name)


__all__ = ["get_llm"]
