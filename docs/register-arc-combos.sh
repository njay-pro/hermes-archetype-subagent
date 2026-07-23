#!/usr/bin/env bash
# register-arc-combos.sh — Register arc-* combos into every Hermes profile.
#
# Usage:
#   ./register-arc-combos.sh           # register all combos in all profiles
#   ./register-arc-combos.sh --dry-run # show what would happen
#
# Behavior:
#   For each profile in default, ana-board, dua-branding, niqah, omca-development:
#     For each combo in arc-consultant1, arc-longHorizon1, arc-speedster1,
#                      arc-highHallucination1:
#       Run: hermes config set custom_providers.0.models.<combo>.context_length 1000000 --force --profile <prof>
#
# Requires: hermes CLI on PATH (or HERMES_BIN env var)
# Exit: 0 on full success, 1 on first failure.

set -euo pipefail

HERMES_BIN="${HERMES_BIN:-/Users/njaypro/.hermes/hermes-agent/venv/bin/hermes}"
PROFILES=(default ana-board dua-branding niqah omca-development)
COMBOS=(arc-consultant1 arc-longHorizon1 arc-speedster1 arc-highHallucination1)
CONTEXT_LENGTH=1000000

DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run)  DRY_RUN=1 ;;
        -h|--help)
            grep '^# ' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

say()  { printf "==> %s\n" "$*"; }
log()  { printf "  %s\n" "$*"; }
fail() { printf "  FAIL: %s\n" "$*" >&2; }

if [ ! -x "$HERMES_BIN" ]; then
    echo "ERROR: hermes CLI not found at $HERMES_BIN" >&2
    exit 1
fi

say "Registering ${#COMBOS[@]} arc-* combo(s) into ${#PROFILES[@]} profile(s)"

for profile in "${PROFILES[@]}"; do
    log "[profile] $profile"
    for combo in "${COMBOS[@]}"; do
        key="custom_providers.0.models.${combo}.context_length"
        if [ "$DRY_RUN" = "1" ]; then
            log "WOULD set $key = $CONTEXT_LENGTH (--profile $profile)"
        else
            if "$HERMES_BIN" config set "$key" "$CONTEXT_LENGTH" --force --profile "$profile" 2>&1 | grep -q '✓'; then
                log "set $combo @ $profile"
            else
                fail "set $combo @ $profile"
                exit 1
            fi
        fi
    done
done

say "Done."
if [ "$DRY_RUN" = "0" ]; then
    say "Restart Hermes gateways to pick up the changes:"
    say "  pkill -f 'hermes.*gateway run --replace'"
    say "  hermes gateway run --replace &"
fi