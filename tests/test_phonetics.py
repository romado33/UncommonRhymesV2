from rhyme_core.phonetics import parse_pron_field, tail_keys


def test_parse_pron_field_accepts_json_string():
    pron = '["T","AE1","K"]'
    toks = parse_pron_field(pron)
    assert toks == ["T", "AE1", "K"]


def test_parse_pron_field_accepts_whitespace_string():
    pron = "W IH1 N D OW0"
    toks = parse_pron_field(pron)
    assert toks == ["W", "IH1", "N", "D", "OW0"]


def test_tail_keys_with_and_without_coda():
    assert tail_keys(["T", "AE1", "K"]) == ("AE1", "K", "AE1-K")
    assert tail_keys(["W", "OW1"]) == ("OW1", "", "OW1")
