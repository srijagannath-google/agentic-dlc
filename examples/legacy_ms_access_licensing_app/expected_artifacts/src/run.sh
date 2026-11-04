#!/bin/sh
# Start the Commercial Buyer Licensing backend (serves the UI and the API on one port). Equals target_stack.json#commands.start
cd "$(dirname "$0")/.." && exec python3 src/backend/server.py "$@"
