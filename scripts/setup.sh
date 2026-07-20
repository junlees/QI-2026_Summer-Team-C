#!/usr/bin/env bash
# One-time local setup: creates a venv and installs backend deps.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

(cd frontend && npm install && npm run build)

echo
echo "Setup done. Activate with: source .venv/bin/activate"
echo "Run the server with:      python backend/app.py"
echo "Rebuild CSS during frontend dev with: cd frontend && npm run watch"
