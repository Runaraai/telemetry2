#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_ACTIVATE="$SCRIPT_DIR/.venv/bin/activate"

if [ ! -f "$VENV_ACTIVATE" ]; then
  echo "run.sh: .venv not found. Run: bash install.sh"
  exit 1
fi

# shellcheck disable=SC1090
source "$VENV_ACTIVATE"
exec python "$SCRIPT_DIR/agent.py" "$@"
