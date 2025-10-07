import unicodedata as ud, importlib, os

def search(q):
    os.environ["UR_LLM_RERANK"]=os.environ["UR_LLM_PATTERN_RERANK"]=os.environ["UR_LLM_OOV_G2P"]="0"
    os.environ["UR_LLM_PHRASE_GEN"]=os.environ["UR_LLM_MULTIWORD_MINE"]=os.environ["UR_LLM_NL_QUERY"]="0"
    import rhyme_core.search as s; importlib.reload(s)
    fn = getattr(s,"find_rhymes",None) or getattr(s,"search",None)
    return fn(q, max_results=20, include_consonant=False)

def as_sets(res):
    u = set((x.get("name","") for x in res.get("uncommon",[]) or res.get("perfect",[])))
    s = set((x.get("name","") for x in res.get("slant",[])))
    m = set((x.get("phrase","") for x in res.get("multiword",[]) or res.get("multi_word",[])))
    return u,s,m

def test_case_insensitive():
    base = as_sets(search("Beat It"))
    assert base == as_sets(search("beat it")) == as_sets(search("BEAT IT"))

def test_diacritics_nfc_nfd():
    cafe_nfc = "café latte"
    cafe_nfd = ud.normalize("NFD", cafe_nfc)
    assert as_sets(search(cafe_nfc)) == as_sets(search(cafe_nfd))

def test_punctuation_whitespace():
    a = as_sets(search("beat it"))
    b = as_sets(search("beat-it"))
    c = as_sets(search("beat  it"))
    assert a == b == c
