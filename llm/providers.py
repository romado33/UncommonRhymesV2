"""Lazy wrappers around optional LLM providers."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional


class _Provider:
    def __init__(self, name: str) -> None:
        self.name = name
        self._openai = None
        self._hf = None

    def _ensure_openai(self):
        if self._openai is not None:
            return self._openai
        try:
            import openai  # type: ignore
        except Exception:
            return None
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        openai.api_key = api_key
        self._openai = openai
        return self._openai

    def _ensure_hf(self):
        if self._hf is not None:
            return self._hf
        try:
            from huggingface_hub import InferenceClient  # type: ignore
        except Exception:
            return None
        token = os.getenv("HUGGINGFACEHUB_API_TOKEN")
        if not token:
            return None
        try:
            self._hf = InferenceClient(token=token)
        except Exception:
            return None
        return self._hf

    def complete_json(self, prompt: str, *, schema_hint: str = "", temperature: float = 0.2, max_tokens: int = 256) -> Dict[str, Any]:
        try:
            if self.name == "openai":
                client = self._ensure_openai()
                if client is None:
                    return {}
                resp = client.ChatCompletion.create(  # type: ignore[attr-defined]
                    model=os.getenv("UR_OPENAI_MODEL", "gpt-4o-mini"),
                    temperature=temperature,
                    messages=[
                        {"role": "system", "content": "Reply ONLY with valid JSON. No prose."},
                        {"role": "user", "content": f"Schema hint: {schema_hint}\n\nTask: {prompt}"},
                    ],
                    max_tokens=max_tokens,
                )
                txt = resp["choices"][0]["message"].get("content") or "{}"
            else:
                client = self._ensure_hf()
                if client is None:
                    return {}
                txt = client.text_generation(
                    prompt=("Reply ONLY with valid JSON. No prose.\n" + prompt),
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                )
            return json.loads(txt)
        except Exception:
            return {}

    def complete_lines(self, prompt: str, *, n: int = 10, temperature: float = 0.7, max_tokens: int = 256) -> List[str]:
        try:
            if self.name == "openai":
                client = self._ensure_openai()
                if client is None:
                    return []
                resp = client.ChatCompletion.create(  # type: ignore[attr-defined]
                    model=os.getenv("UR_OPENAI_MODEL", "gpt-4o-mini"),
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                )
                txt = resp["choices"][0]["message"].get("content") or ""
            else:
                client = self._ensure_hf()
                if client is None:
                    return []
                txt = client.text_generation(
                    prompt=prompt,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                )
            cleaned = [line.strip(" \n\r\t-•") for line in txt.splitlines() if line.strip()]
            return cleaned[:n]
        except Exception:
            return []


def get_provider(name: str) -> Optional[_Provider]:
    if not name:
        return None
    return _Provider(name)


__all__ = ["get_provider"]
