#!/usr/bin/env bash
# Launch the PyExperimenter Dashboard in development mode.
# Usage:
#   ./scripts/dev.sh                          # uses example/ configs
#   ./scripts/dev.sh config.yml db_config.yml # custom configs
#   PORT=9090 ./scripts/dev.sh                # custom port

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

CONFIG="${1:-example/config.yml}"
DB_CONFIG="${2:-example/db_config.yml}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"

echo "PyExperimenter Dashboard – dev mode"
echo "  config    : $CONFIG"
echo "  db-config : $DB_CONFIG"
echo "  address   : http://$HOST:$PORT"
echo ""

# Prefer uv if available, fall back to plain python
if command -v uv &>/dev/null; then
    uv run py-experimenter-dashboard \
        --config "$CONFIG" \
        --db-config "$DB_CONFIG" \
        --host "$HOST" \
        --port "$PORT" \
        --reload
else
    python -m py_experimenter_db.cli \
        --config "$CONFIG" \
        --db-config "$DB_CONFIG" \
        --host "$HOST" \
        --port "$PORT" \
        --reload
fi
