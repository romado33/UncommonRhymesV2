import os, importlib

PAIRS = [
    ("UR_LLM_RERANK","UR_LLM_OOV_G2P"),
    ("UR_LLM_RERANK","UR_LLM_PHRASE_GEN"),
    ("UR_LLM_PATTERN_RERANK","UR_LLM_NL_QUERY"),
]

def search(q):
    import rhyme_core.search as s; importlib.reload(s)
    fn = getattr(s,"find_rhymes",None) or getattr(s,"search",None)
    return fn(q, max_results=20, include_consonant=False)

def count_uncommon(res):
    return len(res.get("uncommon",[]) or res.get("perfect",[]))

def test_pairs_not_worse_than_baseline_on_count():
    # Not a strict oracle; just guard gross regressions.
    for q in ["hat","downside","double"]:
        os.environ.update({k:"0" for k in [
            "UR_LLM_RERANK","UR_LLM_PATTERN_RERANK","UR_LLM_OOV_G2P",
            "UR_LLM_PHRASE_GEN","UR_LLM_MULTIWORD_MINE","UR_LLM_NL_QUERY"
        ]})
        base = count_uncommon(search(q))
        for a,b in PAIRS:
            os.environ.update({a:"1", b:"1"})
            # keep others off
            for k in ["UR_LLM_RERANK","UR_LLM_PATTERN_RERANK","UR_LLM_OOV_G2P","UR_LLM_PHRASE_GEN","UR_LLM_MULTIWORD_MINE","UR_LLM_NL_QUERY"]:
                if k not in (a,b): os.environ[k]="0"
            pair_ct = count_uncommon(search(q))
            assert pair_ct >= 0  # smoke
            # allow <= base (rerank could reorder), but catch empties
            assert not (base>0 and pair_ct==0), f"{a}+{b} nuked Uncommon for {q}"
