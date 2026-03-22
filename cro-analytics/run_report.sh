#!/bin/bash
# Run the weekly CRO report
# Cron: 0 8 * * 1  (every Monday at 8am)
#
# Setup: copy .env.example to .env and fill in your values
# The .env file is gitignored and never committed.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load credentials from local .env (never commit this file)
if [ -f "$SCRIPT_DIR/.env" ]; then
  export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

# Validate required env vars
if [ -z "$HUBSPOT_TOKEN" ] || [ -z "$GA4_KEY_FILE" ]; then
  echo "ERROR: Missing credentials. Copy .env.example to .env and fill in values."
  exit 1
fi

python3 cro_report.py --days 7

echo "Done. Reports saved to $SCRIPT_DIR/reports/"
