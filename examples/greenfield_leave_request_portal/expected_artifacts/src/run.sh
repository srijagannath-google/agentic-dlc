#!/usr/bin/env bash
# Start the Employee Leave & Exception Request Portal (UI + API + payroll stub on one port).
# Must match specs/target_stack.json#commands.start; run from <PROJECT_ROOT>.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 src/backend/server.py "$@"
