#!/usr/bin/env bash
# Best runtime for Track-Smith: Python 3.11 + Magenta (conda).
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_NAME="${TRACK_SMITH_ENV:-track-smith}"
# Magenta 2.1.4 pins numpy 1.21.x — needs Python 3.10 (not 3.11+ or 3.12).
PY_VERSION="${TRACK_SMITH_PY:-3.10}"

if ! command -v conda &>/dev/null; then
  echo "conda not found. Install Miniconda/Anaconda, then re-run."
  exit 1
fi

if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Conda env '$ENV_NAME' already exists — activating and upgrading deps."
else
  echo "Creating conda env '$ENV_NAME' with Python $PY_VERSION..."
  conda create -y -n "$ENV_NAME" "python=${PY_VERSION}" pip
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

pip install --upgrade pip
pip install -r requirements.txt
pip install 'setuptools>=65,<70'

python -c "
from agent.skills.remote_music_gen import available_providers
p = available_providers()
print('Music API:', ', '.join(p) if p else 'none (add UDIO_API_KEY to .env)')
"

echo ""
echo "Done. Run the app:"
echo "  ./run.sh"
echo "  # or: conda activate $ENV_NAME && python plugin_main.py"
