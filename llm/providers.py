from __future__ import annotations
import os, json
from typing import List, Dict, Any
from config import FLAGS

_openai_client = None
_hf_client = None

def _ensure_openai():
    global _openai_client
    if _openai_client is None:
        import openai  # type: ignore
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        openai.api_key = api_key
        _openai_client = openai
    return _openai_client

def _ensure_hf():
    global _hf_client
    if _hf_client is None:
        from huggingface_hub import InferenceClient  # type: ignore
        token = os.getenv("HUGGINGFACEHUB_API_TOKEN")
        if not token:
            raise RuntimeError("HUGGINGFACEHUB_API_TOKEN not set")
        _hf_client = InferenceClient(token=token)
    return _hf_client

def complete_json(prompt: str, schema_hint: str = "", temperature: float = 0.2) -> Dict[str, Any]:
    if FLAGS.PROVIDER == "openai":
        client = _ensure_openai()
        resp = client.chat.completions.create(
            model=os.getenv("UR_OPENAI_MODEL", "gpt-4o-mini"),
            temperature=temperature,
            messages=[
                {"role": "system", "content": "Reply ONLY with valid JSON. No prose."},
                {"role": "user", "content": f"Schema hint: {schema_hint}\n\nTask: {prompt}"},
            ],
            max_tokens=FLAGS.MAX_TOKENS,
        )
        txt = resp.choices[0].message.content or "{}"
    else:
        client = _ensure_hf()
        txt = client.text_generation(
            prompt=("Reply ONLY with valid JSON. No prose.\n" + prompt),
            max_new_tokens=FLAGS.MAX_TOKENS,
            temperature=temperature,
        )
    try:
        return json.loads(txt)
    except Exception:
        return {}

def complete_lines(prompt: str, n: int = 10, temperature: float = 0.7) -> List[str]:
    try:
        if FLAGS.PROVIDER == "openai":
            client = _ensure_openai()
            resp = client.chat.completions.create(
                model=os.getenv("UR_OPENAI_MODEL", "gpt-4o-mini"),
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=min(FLAGS.MAX_TOKENS, 512),
            )
            txt = resp.choices[0].message.content or ""
        else:
            client = _ensure_hf()
            txt = client.text_generation(
                prompt=prompt,
                max_new_tokens=min(FLAGS.MAX_TOKENS, 512),
                temperature=temperature,
            )
        out = [l.strip(" \n\r\t-•") for l in txt.splitlines()]
        return [l for l in out if l][:n]
    except Exception:
        return []