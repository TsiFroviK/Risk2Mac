#!/bin/bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd -P)"
exec "${RISK2MAC_PYTHON:-python3}" "$script_dir/../native/build.py" build "$@"
