#!/usr/bin/env bash
# Run School Management app locally (Mac/Linux)
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo ""
echo "Starting server at http://127.0.0.1:5000"
echo "Login: admin@school.com / support"
echo "Press CTRL+C to stop."
echo ""

python app.py
