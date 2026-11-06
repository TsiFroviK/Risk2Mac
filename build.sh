#!/bin/bash
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd -P)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$root/scripts/build.py" "$@"
