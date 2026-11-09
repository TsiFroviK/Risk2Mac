#!/bin/bash
set -euo pipefail

risk2mac_prepare_steam_overlay() {
    local app_root="$1"
    local steam_root="$HOME/Library/Application Support/Steam/Steam.AppBundle/Steam/Contents/MacOS"
    local renderer="$steam_root/gameoverlayrenderer.dylib"
    local marker="$app_root/Contents/Resources/Risk2MacSteamAppId.txt"
    local app_id="632360" extra="" marker_valid=1 marker_bytes architecture existing

    if [[ ! -f "$app_root/Contents/Plugins/libRisk2MacSteamBridge.dylib" ]]; then
        return 0
    fi
    if [[ "${RISK2MAC_FORCE_LOCAL:-}" == "1" ]]; then
        printf 'Steam overlay: skipped for forced local mode.\n'
        return 0
    fi
    if ! /usr/bin/pgrep -u "$UID" -x steam_osx >/dev/null; then
        printf 'Steam overlay: client is not running; continuing without overlay.\n'
        return 0
    fi
    if [[ ! -f "$renderer" ]]; then
        printf 'Steam overlay: installed renderer is missing; continuing without overlay.\n'
        return 0
    fi
    if [[ -e "$marker" || -L "$marker" ]]; then
        if [[ ! -f "$marker" || -L "$marker" || ! -r "$marker" ]]; then
            marker_valid=0
        elif ! marker_bytes="$(/usr/bin/stat -f%z "$marker")"; then
            marker_valid=0
        elif [[ "$marker_bytes" -lt 1 || "$marker_bytes" -gt 7 ]]; then
            marker_valid=0
        else
            {
                IFS= read -r app_id || [[ -n "$app_id" ]] || marker_valid=0
                if IFS= read -r extra || [[ -n "$extra" ]]; then
                    marker_valid=0
                fi
            } < "$marker"
        fi
        case "$app_id" in
            632360|480) ;;
            *) marker_valid=0 ;;
        esac
        if [[ "$marker_valid" != 1 ]]; then
            printf 'Steam overlay: invalid session marker; continuing without overlay.\n'
            return 0
        fi
    fi
    if ! architecture="$(/usr/bin/uname -m)"; then
        printf 'Steam overlay: cannot determine architecture; continuing without overlay.\n'
        return 0
    fi
    case "$architecture" in
        arm64|x86_64) ;;
        *) printf 'Steam overlay: unsupported architecture; continuing without overlay.\n'; return 0 ;;
    esac
    if ! /usr/bin/codesign --verify --strict --architecture "$architecture" \
        -R '=anchor apple generic and certificate leaf[subject.OU] = "MXGJJ98X76"' "$renderer"; then
        printf 'Steam overlay: Valve signature verification failed; continuing without overlay.\n'
        return 0
    fi
    existing="${DYLD_INSERT_LIBRARIES:-}"
    case ":$existing:" in
        *":$renderer:"*) ;;
        *) export DYLD_INSERT_LIBRARIES="$renderer${existing:+:$existing}" ;;
    esac
    export SteamAppId="$app_id" SteamGameId="$app_id" SteamOverlayGameId="$app_id"
    printf 'Steam overlay: enabled for AppID %s (%s).\n' "$app_id" "$architecture"
}

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
risk2mac_prepare_steam_overlay "$app_dir"
exec "$bin_dir/Risk of Rain 2 Player" --arm64-solo-probe --disableCrossplay -logFile "$unity_log" "$@"
