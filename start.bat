@echo off
rem Start formshift-server for local dev: loopback, port 7457, CORS allowed
rem for the Vite dev server at http://localhost:5173.
rem Extra args pass through, e.g. `start.bat --port 0` or `start.bat --extensions-dir extensions`.
rem To disable CORS, edit out the --cors-origin flag below.
cd /d "%~dp0"
uv run formshift-server --cors-origin http://localhost:5173 %*
