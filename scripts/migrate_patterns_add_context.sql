-- Adds optional context columns to the rap patterns table and helpful indices.
-- NOTE: SQLite does not support IF NOT EXISTS for ADD COLUMN; run this once.
-- If columns already exist, you can ignore the resulting errors or remove the lines.

BEGIN TRANSACTION;

-- If your table is not named "patterns", change the name in all statements below.

-- Add optional columns (run once)
ALTER TABLE patterns ADD COLUMN lyric_context TEXT;
ALTER TABLE patterns ADD COLUMN source_context TEXT;
ALTER TABLE patterns ADD COLUMN target_context TEXT;

-- Helpful indices when present (no-op if missing columns)
CREATE INDEX IF NOT EXISTS idx_patterns_rime_key  ON patterns(rime_key);
CREATE INDEX IF NOT EXISTS idx_patterns_vowel_key ON patterns(vowel_key);
CREATE INDEX IF NOT EXISTS idx_patterns_coda_key  ON patterns(coda_key);

COMMIT;
