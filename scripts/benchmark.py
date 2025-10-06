#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Formal benchmark for Uncommon Rhymes V2.

- Deterministic baseline + one-flag-at-a-time LLM runs
- Provenance snapshot (git/cmu/patterns hashes, py/sqlite/platform, config)
- Per-query latency (ms) and error fields (search/patterns/prosody)
- Golden expectations (WARN by default; --golden_fail to hard-fail)
- Caps per bucket (default 20)
- Writes CSV + a plain text file listing the queries used
"""

import os, sys, csv, json, argparse, importlib, subprocess, hashlib, platform, sqlite3, random, time
from pathlib import Path
from typing import Dict, List, Any, Tuple

LLM_FLAGS = [
    "UR_LLM_RERANK",
    "UR_LLM_PATTERN_RERANK",
    "UR_LLM_OOV_G2P",
    "UR_LLM_PHRASE_GEN",
    "UR_LLM_MULTIWORD_MINE",
    "UR_LLM_NL_QUERY",
]

def file_sha256(p: Path) -> str:
    if not p or not p.exists():
        return ""
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]

def get_git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()[:12]
    except Exception:
        return ""

def get_sqlite_version() -> str:
    try:
        return sqlite3.sqlite_version
    except Exception:
        return ""

def compact_json(obj: Any) -> str:
    try:
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        return ""

FIXED_SEED = 1337
def set_determinism():
    random.seed(FIXED_SEED)
    os.environ["PYTHONHASHSEED"] = str(FIXED_SEED)
    os.environ["UR_LLM_TEMPERATURE"] = "0"
    os.environ["UR_LLM_TOP_P"] = "1"

def import_core():
    # Force clean reload so env toggles take effect
    for name in list(sys.modules.keys()):
        if name in ("config", "rhyme_core.search", "rhyme_core.prosody", "rhyme_core.patterns"):
            importlib.reload(sys.modules[name])
    import config  # type: ignore
    import rhyme_core.search as search  # type: ignore
    import rhyme_core.prosody as prosody  # type: ignore
    import rhyme_core.patterns as patterns  # type: ignore
    return config, search, prosody, patterns

def prosody_info(prosody_mod, query: str) -> Tuple[Any, Any, Any]:
    syl = getattr(prosody_mod, "syllable_count", lambda x: None)(query)
    stress = getattr(prosody_mod, "stress_pattern_str", lambda x: None)(query)
    metre = getattr(prosody_mod, "metrical_name", lambda x: None)(stress) if stress else None
    return syl, stress, metre

def find_all(search_mod, query: str, cap: int) -> Dict[str, List[Dict[str, Any]]]:
    if hasattr(search_mod, "find_rhymes"):
        res = search_mod.find_rhymes(query, max_results=cap, include_consonant=False)
    elif hasattr(search_mod, "search"):
        res = search_mod.search(query, max_results=cap, include_consonant=False)
    else:
        raise RuntimeError("No search entry point found in rhyme_core.search.")
    out = {
        "uncommon": res.get("uncommon") or res.get("perfect") or [],
        "slant":    res.get("slant") or [],
        "multi":    res.get("multiword") or res.get("multi_word") or [],
    }
    # Deterministic tie-breakers (tail/rime, then surface, then rarity desc)
    def sort_items(lst, name_key="name"):
        return sorted(
            lst,
            key=lambda it: (
                str(it.get("tail_key") or it.get("rime_key") or ""),
                str(it.get(name_key) or it.get("phrase") or ""),
                -float(it.get("rarity", 0.0)),
            ),
        )[:cap]
    out["uncommon"] = sort_items(out["uncommon"])
    out["slant"]    = sort_items(out["slant"])
    out["multi"]    = sort_items(out["multi"], name_key="phrase")
    return out

def rap_patterns_for(patterns_mod, query: str, cap: int) -> List[Dict[str, Any]]:
    fn = None
    if hasattr(patterns_mod, "find_patterns_by_keys_enriched"):
        fn = patterns_mod.find_patterns_by_keys_enriched
    elif hasattr(patterns_mod, "find_patterns_by_keys"):
        fn = patterns_mod.find_patterns_by_keys
    if not fn:
        return []
    items = fn(query, limit=cap) or []
    items = sorted(items, key=lambda r: (str(r.get("source") or ""), str(r.get("target") or ""), str(r.get("context") or "")))[:cap]
    return items

def all_llm_off():
    for k in LLM_FLAGS:
        os.environ[k] = "0"

def one_llm_on(flag: str):
    all_llm_off()
    os.environ[flag] = "1"

def snapshot_config_env() -> Dict[str, Any]:
    keys = [
        "UR_LLM_PROVIDER",
        "UR_OPENAI_MODEL",
        "UR_LLM_TIMEOUT_S",
        "UR_LLM_MAX_TOKENS",
        "UR_LLM_TEMPERATURE",
        "UR_LLM_TOP_P",
        *LLM_FLAGS,
    ]
    return {k: os.environ.get(k, "") for k in keys}

def load_golden(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except Exception:
        print("⚠️ PyYAML not installed; skipping golden checks.")
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

def golden_check(query: str, sets: Dict[str, List[Dict[str, Any]]], g: Dict[str, Any]):
    if query not in g:
        return "OK", []
    must_any = (g[query] or {}).get("must_include_any") or []
    if not must_any:
        return "OK", []
    names = set()
    for k in ("uncommon", "slant"):
        for it in sets.get(k, []):
            s = (it.get("name") or "").lower()
            if s:
                names.add(s)
    for it in sets.get("multi", []):
        s = (it.get("phrase") or "").lower()
        if s:
            names.add(s)
    if not any(term.lower() in names for term in must_any):
        return "WARN", [f"missing_any_of={must_any}"]
    return "OK", []

def run_condition(condition: str, terms: List[str], cap: int, files: Dict[str, Path], goldens: Dict[str, Any], rows: List[Dict[str, Any]], golden_fail: bool):
    set_determinism()
    config, search_mod, prosody_mod, patterns_mod = import_core()

    prov = {
        "git_sha": get_git_sha(),
        "cmu_hash": file_sha256(files.get("cmu")),
        "patterns_hash": file_sha256(files.get("patterns")),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "sqlite_version": get_sqlite_version(),
        "config_snapshot": snapshot_config_env(),
        "schema_version": 1
    }
    prov_str = compact_json(prov)

    for q in terms:
        q = q.strip()
        if not q:
            continue
        try:
            import unicodedata as ud
            qn = ud.normalize("NFC", q)
        except Exception:
            qn = q

        # Prosody
        syl = stress = metre = None
        try:
            syl, stress, metre = prosody_info(prosody_mod, qn)
            error_prosody = ""
        except Exception as e:
            error_prosody = f"{type(e).__name__}: {e}"

        # Search
        t0 = time.perf_counter()
        try:
            buckets = find_all(search_mod, qn, cap=cap)
            error_search = ""
        except Exception as e:
            buckets = {"uncommon": [], "slant": [], "multi": []}
            error_search = f"{type(e).__name__}: {e}"
        t1 = time.perf_counter()
        latency_ms_search = int((t1 - t0) * 1000)

        # Rap patterns
        t2 = time.perf_counter()
        try:
            rap = rap_patterns_for(patterns_mod, qn, cap=cap)
            error_patterns = ""
        except Exception as e:
            rap = []
            error_patterns = f"{type(e).__name__}: {e}"
        t3 = time.perf_counter()
        latency_ms_patterns = int((t3 - t2) * 1000)

        consonant_violation = any((it.get("type") == "consonant") for it in buckets.get("slant", []))

        def fmt(lst, name_key="name", type_key="type", phrase_fallback="phrase"):
            out = []
            for it in lst[:cap]:
                label = (it.get(name_key) or it.get(phrase_fallback) or "").strip()
                t = (it.get(type_key) or it.get("kind") or "").strip()
                out.append(f"{label}::{t}" if t else label)
            return " | ".join(out)

        uncommon_items = fmt(buckets.get("uncommon", []))
        slant_items    = fmt(buckets.get("slant", []))
        multi_items    = fmt(buckets.get("multi", []), name_key="phrase")

        rap_fmt_list = []
        for r in rap[:cap]:
            src = (r.get("source") or r.get("src") or "").strip()
            tgt = (r.get("target") or r.get("tgt") or "").strip()
            ctx = (r.get("context") or r.get("snippet") or "").strip()
            pair = f"{src}→{tgt}" if (src or tgt) else (r.get("phrase") or "").strip()
            rap_fmt_list.append(f"{pair}::{ctx}" if ctx else pair)
        rap_items = " | ".join(rap_fmt_list)
        rap_empty_reason = "" if rap else "NO_MATCH_OR_NOT_IN_CORPUS"

        golden_state, warns = golden_check(qn, buckets, goldens)
        if golden_fail and golden_state != "OK":
            golden_state = "FAIL"

        rows.append({
            "test_run_id": str(int(time.time())),
            "condition": condition,
            "llm_flag_on": "NONE" if condition == "baseline" else condition,
            "query": qn,
            "syllables": syl if syl is not None else "",
            "stress_pattern": stress or "",
            "metre": metre or "",
            "uncommon_count": len(buckets.get("uncommon", [])),
            "slant_count": len(buckets.get("slant", [])),
            "multiword_count": len(buckets.get("multi", [])),
            "rap_count": len(rap),
            "uncommon_items": uncommon_items,
            "slant_items": slant_items,
            "multiword_items": multi_items,
            "rap_items": rap_items,
            "rap_empty_reason": rap_empty_reason,
            "consonant_violation": str(bool(consonant_violation)),
            "latency_ms_search": latency_ms_search,
            "latency_ms_patterns": latency_ms_patterns,
            "error_prosody": error_prosody,
            "error_search": error_search,
            "error_patterns": error_patterns,
            "provenance": prov_str,
            "golden_status": golden_state if not warns else f"{golden_state}:{','.join(warns)}",
        })

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--terms", default="data/test_terms.txt")
    ap.add_argument("--goldens", default="data/golden_expectations.yaml")
    ap.add_argument("--out", default="results/benchmark.csv")
    ap.add_argument("--cap", type=int, default=20, help="Max items per bucket.")
    ap.add_argument("--golden_fail", action="store_true", help="Mark golden violations as FAIL instead of WARN.")
    args = ap.parse_args()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)

    terms_path = Path(args.terms)
    if not terms_path.exists():
        print(f"❌ Terms file not found: {terms_path}")
        sys.exit(1)
    terms = [ln.strip() for ln in terms_path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    # Log queries used
    queries_log = Path(args.out).with_suffix(".queries_used.txt")
    queries_log.write_text("\n".join(terms) + "\n", encoding="utf-8")

    cmu_sqlite = Path("data/words_index.sqlite")
    patterns_db = None
    for cand in ("data/patterns.db", "data/patterns_small.db"):
        p = Path(cand)
        if p.exists():
            patterns_db = p
            break
    files = {"cmu": cmu_sqlite if cmu_sqlite.exists() else None, "patterns": patterns_db}

    goldens = load_golden(Path(args.goldens))
    rows: List[Dict[str, Any]] = []

    all_llm_off()
    run_condition("baseline", terms, cap=args.cap, files=files, goldens=goldens, rows=rows, golden_fail=args.golden_fail)
    for flag in LLM_FLAGS:
        all_llm_off(); os.environ[flag] = "1"
        run_condition(flag, terms, cap=args.cap, files=files, goldens=goldens, rows=rows, golden_fail=args.golden_fail)

    fieldnames = [
        "test_run_id","condition","llm_flag_on","query",
        "syllables","stress_pattern","metre",
        "uncommon_count","slant_count","multiword_count","rap_count",
        "uncommon_items","slant_items","multiword_items","rap_items",
        "rap_empty_reason","consonant_violation",
        "latency_ms_search","latency_ms_patterns",
        "error_prosody","error_search","error_patterns",
        "provenance","golden_status",
    ]
    with Path(args.out).open("w", newline="", encoding="utf-8") as cf:
        w = csv.DictWriter(cf, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"✅ Wrote {len(rows)} rows → {args.out}")
    print(f"📝 Logged queries → {queries_log}")

if __name__ == "__main__":
    os.environ.setdefault("UR_LLM_TEMPERATURE", "0")
    os.environ.setdefault("UR_LLM_TOP_P", "1")
    main()
