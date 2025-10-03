from rhyme_core.index_builder import build_words_index

if __name__ == "__main__":
    build_words_index("data/cmudict-0.7b.txt", "data/words_index.sqlite")
    print("Built data/words_index.sqlite")
