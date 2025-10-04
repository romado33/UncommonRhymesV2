import pytest
from rhyme_core.search import search_word

CASES = [
    ("sister", 30),
    ("rhyme", 30),
    ("time", 30),
    ("music", 20),
    ("orange", 5),
    ("again", 20),
]

@pytest.mark.parametrize("word,min_count", CASES)
def test_counts(word, min_count):
    res = search_word(word, max_results=200)
    assert len(res) >= min_count

def test_types_present():
    res = search_word("sister", max_results=100, include_pron=True)
    rtypes = {r["rhyme_type"].split()[-1] for r in res}  # strip 'multisyllabic ' prefix if present
    assert "perfect" in rtypes
    assert ("assonant" in rtypes) or ("consonant" in rtypes)
