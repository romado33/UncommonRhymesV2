import importlib, os

def load_core():
    for name in list(__import__('sys').modules.keys()):
        if name in ("rhyme_core.search","rhyme_core.prosody"):
            importlib.reload(__import__('sys').modules[name])
    import rhyme_core.search as search
    import rhyme_core.prosody as prosody
    return search, prosody

def test_no_consonant_in_baseline_slant():
    os.environ.update({k:"0" for k in [
        "UR_LLM_RERANK","UR_LLM_PATTERN_RERANK","UR_LLM_OOV_G2P",
        "UR_LLM_PHRASE_GEN","UR_LLM_MULTIWORD_MINE","UR_LLM_NL_QUERY"
    ]})
    search, _ = load_core()
    fn = getattr(search,"find_rhymes",None) or getattr(search,"search",None)
    for q in ["hat","downside","double","rough","queue"]:
        res = fn(q, max_results=20, include_consonant=False)
        assert all((it.get("type")!="consonant" for it in res.get("slant",[]))), f"Consonant slant leaked for {q}"
