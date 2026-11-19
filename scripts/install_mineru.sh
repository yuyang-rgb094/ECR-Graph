#!/usr/bin/env bash
# Install MinerU locally in its own virtual environment (documents never leave this machine).
#
# MinerU 4.x requires Python >= 3.11 (< 3.15). This script uses `uv` to fetch a
# suitable Python, so the toolkit's own Python version does not matter.
#
# Usage:  scripts/install_mineru.sh [install_dir] [tier]
#         install_dir defaults to ~/.ecr-graph/mineru, tier to "standard"
#         (basic | standard | advanced — see docs/LARGE-DOCUMENTS.md for RAM needs)
set -euo pipefail

DIR="${1:-$HOME/.ecr-graph/mineru}"
TIER="${2:-standard}"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Install it first:  python3 -m pip install --user uv   (or see https://docs.astral.sh/uv/)"
  exit 1
fi

echo "Creating virtual environment in: $DIR"
uv venv "$DIR" --python 3.12
# shellcheck disable=SC1091
source "$DIR/bin/activate"
uv pip install -U "mineru>=4.0,<5"

echo "Downloading models for tier '$TIER' (several GB; one-time)…"
mineru-kit models download --tier "$TIER"

cat <<EOF

Done. Add MinerU to your PATH for ECR-Graph, e.g.:
  export PATH="$DIR/bin:\$PATH"
Then check:  python3 -m ecr_graph mineru doctor
EOF
