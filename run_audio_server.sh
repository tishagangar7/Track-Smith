#!/usr/bin/env bash
# Run the Aux audio server on DGX (port 8001).
# Requires: pip install fastapi uvicorn transformers torch scipy demucs

set -euo pipefail

cd "$(dirname "$0")"

export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-0}"
export MUSICGEN_MODEL="${MUSICGEN_MODEL:-facebook/musicgen-small}"
export AUDIO_SERVER_PORT="${AUDIO_SERVER_PORT:-8001}"

echo "Starting Aux audio server on port $AUDIO_SERVER_PORT"
echo "Model: $MUSICGEN_MODEL"

python -m agent.audio_server
