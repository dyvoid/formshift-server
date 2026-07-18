#!/usr/bin/env bash
# Start formshift-server for local dev: loopback, port 7457, CORS allowed
# for the Vite dev server at http://localhost:5173.
# Extra args pass through, e.g. `./start.sh --port 0` or `./start.sh --extensions-dir extensions`.
# To disable CORS, edit out the --cors-origin flag below.
set -euo pipefail
cd "$(dirname "$0")"
exec uv run formshift-server --cors-origin http://localhost:5173 "$@"
