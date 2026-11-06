#!/bin/bash
set -euo pipefail

bin_dir="$(cd "$(dirname "$0")" && pwd -P)"
app_dir="$(cd "$bin_dir/../.." && pwd -P)"
log_dir="$HOME/Library/Logs/Risk Of Rain 2"
mkdir -p "$log_dir"
run_id="$(/bin/date '+%Y-%m-%d_%H-%M-%S')-$$"
unity_log="$log_dir/Unity-$run_id.log"
launcher_log="$log_dir/Launcher-$run_id.log"
: > "$unity_log"
: > "$launcher_log"
/bin/ln -sfn "$(/usr/bin/basename "$unity_log")" "$log_dir/Latest-Unity.log"
/bin/ln -sfn "$(/usr/bin/basename "$launcher_log")" "$log_dir/Latest-Launcher.log"
exec >> "$launcher_log" 2>&1
printf 'Risk2Mac\nApplication: %s\nUnity log: %s\n' "$app_dir" "$unity_log"
/usr/bin/sw_vers
/usr/bin/uname -m
/bin/cat "$app_dir/Contents/Resources/PortBuild.txt"
cd "$app_dir/Contents"
export UNITY_DISPLAYLINK_BLIT=0
exec "$bin_dir/Risk of Rain 2 Player" --arm64-solo-probe --disableCrossplay -logFile "$unity_log" "$@"
