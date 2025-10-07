import os, importlib
from pathlib import Path

def reload_core():
    for name in list(__import__('sys').modules.keys()):
        if name in ("config","rhyme_core.search","rhyme_core.prosody","rhyme_core.patterns"):
            importlib.reload(__import__('sys').modules[name])
    import rhyme_core.search as search
    return search

def run_once(q):
    os.environ["UR_LLM_TEMPERATURE"]="0"; os.environ["UR_LLM_TOP_P"]="1"
    os.environ["UR_LLM_RERANK"]=os.environ["UR_LLM_PATTERN_RERANK"]=os.environ["UR_LLM_OOV_G2P"]="0"
    os.environ["UR_LLM_PHRASE_GEN"]=os.environ["UR_LLM_MULTIWORD_MINE"]=os.environ["UR_LLM_NL_QUERY"]="0"
    search = reload_core()
    fn = getattr(search,"find_rhymes",None) or getattr(search,"search",None)
    res = fn(q, max_results=20, include_consonant=False)
    # normalize
    perf = tuple(sorted((x.get("name","") for x in res.get("uncommon",[]) or res.get("perfect",[]))))
    slnt = tuple(sorted((x.get("name","") for x in res.get("slant",[]))))
    mult = tuple(sorted((x.get("phrase","") for x in res.get("multiword",[]) or res.get("multi_word",[]))))
    return perf, slnt, mult

def test_three_runs_identical():
    for q in Path("data/test_terms.txt").read_text(encoding="utf-8").splitlines():
        q=q.strip()
        if not q: continue
        r1, r2, r3 = run_once(q), run_once(q), run_once(q)
        assert r1 == r2 == r3, f"Non-deterministic for query: {q}"
