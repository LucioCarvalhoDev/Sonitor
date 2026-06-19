#!/usr/bin/env bash
# One-shot setup after `git clone`: create the virtualenv, install
# dependencies, and seed a local `.env`. Idempotent — safe to re-run.
#
# Usage:
#   ./scripts/init.sh            # runtime + dev deps (includes pytest)
#   ./scripts/init.sh --no-dev   # runtime deps only (tomli, tomli-w)
#
# Override the interpreter used to bootstrap the venv with PYTHON=...:
#   PYTHON=python3.10 ./scripts/init.sh
set -euo pipefail

# Resolve the repo root from this script's location so it works from anywhere.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

PYTHON="${PYTHON:-python3}"
VENV="$HERE/.venv"
DEV=1

for arg in "$@"; do
    case "$arg" in
        --no-dev) DEV=0 ;;
        -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "init.sh: unknown option '$arg'" >&2; exit 2 ;;
    esac
done

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "init.sh: '$PYTHON' not found — install Python 3.10+ or set PYTHON=..." >&2
    exit 1
fi

# 1. Virtualenv.
if [ ! -d "$VENV" ]; then
    echo "==> creating virtualenv at .venv"
    "$PYTHON" -m venv "$VENV"
else
    echo "==> reusing existing virtualenv at .venv"
fi

VPY="$VENV/bin/python"

# 2. Dependencies.
echo "==> upgrading pip"
"$VPY" -m pip install --upgrade --quiet pip

if [ "$DEV" -eq 1 ]; then
    echo "==> installing dev dependencies (requirements-dev.txt)"
    "$VPY" -m pip install --quiet -r requirements-dev.txt
else
    echo "==> installing runtime dependencies (requirements.txt)"
    "$VPY" -m pip install --quiet -r requirements.txt
fi

# 3. Local config.
if [ ! -f "$HERE/.env" ]; then
    echo "==> seeding .env from .env.sample"
    cp "$HERE/.env.sample" "$HERE/.env"
else
    echo "==> .env already present, leaving it untouched"
fi

echo
echo "Setup complete. Next steps:"
echo "  source .venv/bin/activate        # or run via: SONITOR_PYTHON=.venv/bin/python ./sonitor ..."
echo "  ./sonitor print --metric sys-uptime"
[ "$DEV" -eq 1 ] && echo "  .venv/bin/python -m pytest       # run the test suite"
exit 0
