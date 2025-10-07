BEGIN;
DROP TABLE IF EXISTS rap_lines;
CREATE TABLE rap_lines(
  key    TEXT PRIMARY KEY,
  lyric  TEXT NOT NULL,
  artist TEXT,
  song   TEXT
);
CREATE INDEX IF NOT EXISTS idx_rap_lyric ON rap_lines(lyric);
COMMIT;
