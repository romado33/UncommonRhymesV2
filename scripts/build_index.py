import logging

from rhyme_core.index_builder import build_words_index
from rhyme_core.logging_utils import setup_logging

setup_logging()
log = logging.getLogger(__name__)

if __name__ == "__main__":
    build_words_index("data/cmudict-0.7b.txt", "data/words_index.sqlite")
    log.info("Built data/words_index.sqlite")
