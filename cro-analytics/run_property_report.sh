#!/bin/bash
# Run the weekly property page CRO cycle
# Cron: 0 9 * * 1  (every Monday at 9am)
#
# Setup: copy .env.example to .env and fill in your values
# The .env file is gitignored and never committed.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load credentials from local .env
if [ -f "$SCRIPT_DIR/.env" ]; then
  export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
fi

# Validate required env vars
if [ -z "$HUBSPOT_TOKEN" ] || [ -z "$GA4_KEY_FILE" ]; then
  echo "ERROR: Missing credentials. Copy .env.example to .env and fill in values."
  exit 1
fi

python3 weekly_cycle_property.py

echo "Done. Briefing saved to property-pages/"
