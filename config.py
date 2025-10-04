from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Flags:
    LLM_RERANK: bool = bool(int(os.getenv("UR_LLM_RERANK", "0")))
    LLM_OOV_G2P: bool = bool(int(os.getenv("UR_LLM_OOV_G2P", "0")))
    LLM_PHRASE_GEN: bool = bool(int(os.getenv("UR_LLM_PHRASE_GEN", "0")))
    LLM_PATTERN_RERANK: bool = bool(int(os.getenv("UR_LLM_PATTERN_RERANK", "0")))
    LLM_MULTIWORD_MINE: bool = bool(int(os.getenv("UR_LLM_MULTIWORD_MINE", "0")))
    LLM_NL_QUERY: bool = bool(int(os.getenv("UR_LLM_NL_QUERY", "0")))
    PROVIDER: str = os.getenv("UR_LLM_PROVIDER", "openai")  # "openai" or "hf"
    TIMEOUT_S: float = float(os.getenv("UR_LLM_TIMEOUT_S", "8.0"))
    MAX_TOKENS: int = int(os.getenv("UR_LLM_MAX_TOKENS", "256"))
FLAGS = Flags()