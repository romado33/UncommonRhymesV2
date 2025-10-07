#!/usr/bin/env bash
set -euo pipefail
sqlite3 data/patterns_small.db ".output data/patterns_small.sql" ".dump"
echo "Wrote data/patterns_small.sql"
