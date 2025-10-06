"""Runtime configuration flags for UncommonRhymesV2.

The flags intentionally rely on environment variables so deployments can
stay deterministic without code changes.  Every flag defaults to a safe
value (no LLM access, consonant rhymes disabled, fallbacks allowed).
"""
from __future__ import annotations

import os
from typing import Any, Dict


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default) == "1"


def _env_int(name: str, default: str) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return int(default)


class _Flags(dict):
    def __getattr__(self, name: str) -> Any:  # pragma: no cover - compatibility shim
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


FLAGS: Dict[str, Any] = _Flags({
    "TOP_K": _env_int("TOP_K", "100"),
    "DISABLE_CONSONANT_RHYMES": _env_bool("DISABLE_CONSONANT_RHYMES", "1"),
    "ALLOW_FALLBACK": _env_bool("ALLOW_FALLBACK", "1"),
    "USE_LLM": _env_bool("USE_LLM", "0"),
    "LLM_PROVIDER": os.getenv("LLM_PROVIDER", "openai"),
    "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
    # Legacy attribute names preserved for compatibility with older modules.
    "LLM_RERANK": False,
    "LLM_OOV_G2P": False,
    "LLM_PHRASE_GEN": False,
    "LLM_PATTERN_RERANK": False,
    "LLM_MULTIWORD_MINE": False,
    "LLM_NL_QUERY": False,
})

__all__ = ["FLAGS"]
