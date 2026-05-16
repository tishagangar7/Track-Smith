#!/usr/bin/env bash
# Launch Track-Smith with the recommended conda env.
set -euo pipefail
cd "$(dirname "$0")"
ENV_NAME="${TRACK_SMITH_ENV:-track-smith-py310}"

if ! command -v conda &>/dev/null; then
  echo "conda not found — run: python plugin_main.py"
  exec python plugin_main.py
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"
exec python plugin_main.py
