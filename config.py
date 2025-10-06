from __future__ import annotations
import os
from dataclasses import dataclass

# Optional: load .env if python-dotenv is installed (safe no-op otherwise)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

def _env_bool(name: str, default: str = "0") -> bool:
    return bool(int(os.getenv(name, default)))

@dataclass(frozen=True)
class Flags:
    # Feature flags (ALL default OFF)
    LLM_RERANK: bool           = _env_bool("UR_LLM_RERANK", "0")
    LLM_OOV_G2P: bool          = _env_bool("UR_LLM_OOV_G2P", "0")
    LLM_PHRASE_GEN: bool       = _env_bool("UR_LLM_PHRASE_GEN", "0")
    LLM_PATTERN_RERANK: bool   = _env_bool("UR_LLM_PATTERN_RERANK", "0")
    LLM_MULTIWORD_MINE: bool   = _env_bool("UR_LLM_MULTIWORD_MINE", "0")
    LLM_NL_QUERY: bool         = _env_bool("UR_LLM_NL_QUERY", "0")

    # Provider + runtime knobs
    PROVIDER: str   = os.getenv("UR_LLM_PROVIDER", "openai")  # "openai" or "hf"
    TIMEOUT_S: float = float(os.getenv("UR_LLM_TIMEOUT_S", "8.0"))
    MAX_TOKENS: int  = int(os.getenv("UR_LLM_MAX_TOKENS", "256"))

FLAGS = Flags()

__all__ = ["FLAGS", "Flags"]
