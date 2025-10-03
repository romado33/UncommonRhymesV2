import os, sqlite3, json
from rhyme_core.search import search_word

def _fake_db(tmp_path):
    os.makedirs("data", exist_ok=True)
    con = sqlite3.connect("data/words_index.sqlite")
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS words(
            word TEXT PRIMARY KEY,
            pron TEXT NOT NULL,
            syls INTEGER NOT NULL,
            k1   TEXT NOT NULL,
            k2   TEXT NOT NULL
        );
    """)
    # minimal fake entry set
    w = "window"
    pron = json.dumps(["W","IH1","N","D","OW0"])
    cur.execute("INSERT OR REPLACE INTO words VALUES(?,?,?,?,?)",
                (w, pron, 2, json.dumps(["IH1","N","D","OW0"]), json.dumps(["IH1","N","D","OW0"])))
    cur.execute("INSERT OR REPLACE INTO words VALUES(?,?,?,?,?)",
                ("thin-blow", pron, 2, json.dumps(["IH1","N","D","OW0"]), json.dumps(["IH1","N","D","OW0"])))
    con.commit(); con.close()

def test_search_smoke(tmp_path):
    _fake_db(tmp_path)
    res = search_word("window")
    assert isinstance(res, list)
    assert len(res) >= 1
