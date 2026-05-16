#!/usr/bin/env bash
# Run the Aux audio server on DGX (port 8001).
# Creates a local venv so Ubuntu/Debian PEP 668 system Python is left alone.

set -euo pipefail

cd "$(dirname "$0")"

export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-0}"
export MUSICGEN_MODEL="${MUSICGEN_MODEL:-facebook/musicgen-melody}"
export AUDIO_SERVER_PORT="${AUDIO_SERVER_PORT:-8001}"

VENV_DIR="${AUDIO_SERVER_VENV:-.venv-audio-server}"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "Creating audio server venv: $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements-audio-server.txt

echo "Starting Aux audio server on port $AUDIO_SERVER_PORT"
echo "Model: $MUSICGEN_MODEL"

"$VENV_DIR/bin/python" -m agent.audio_server
