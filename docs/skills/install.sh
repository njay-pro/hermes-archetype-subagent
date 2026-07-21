#!/usr/bin/env bash
# install.sh — Install all skills in this folder to every Hermes profile + AGENT-* workspace.
#
# Usage:
#   ./install.sh                 # install (idempotent — safe to re-run)
#   ./install.sh --dry-run       # show what would be done, change nothing
#   ./install.sh --uninstall     # remove all symlinks this script created
#
# Behavior:
#   - Symlinks each skill/<name>/ to the 9 standard destinations
#   - Skips targets that already point at this skill (idempotent)
#   - Logs every action with clear prefix
#
# Exits 0 on success, 1 on the first hard failure (after logging the rest).

set -euo pipefail

# ── paths ────────────────────────────────────────────────────────────────

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

DRY_RUN=0
UNINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --dry-run)    DRY_RUN=1 ;;
        --uninstall)  UNINSTALL=1 ;;
        -h|--help)
            grep '^# ' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown arg: $arg" >&2
            exit 2
            ;;
    esac
done

# ── skill discovery ────────────────────────────────────────────────────
# Walk this folder's children. Each child that has a SKILL.md is a skill.

SKILL_DIRS=()
for dir in "$SCRIPT_DIR"/*/; do
    [ -d "$dir" ] || continue
    [ -f "$dir/SKILL.md" ] || continue
    SKILL_DIRS+=("$(basename "$dir")")
done

if [ ${#SKILL_DIRS[@]} -eq 0 ]; then
    echo "No skills found in $SCRIPT_DIR (no subdirectory has a SKILL.md)" >&2
    exit 1
fi

# ── destination discovery ──────────────────────────────────────────────
# 9 standard destinations per the OMCA skill hub rules.

DESTINATIONS=(
    # Hermes global + per-profile skill dirs
    "$HERMES_HOME/skills"
    "$HERMES_HOME/profiles/default/skills"
    "$HERMES_HOME/profiles/ana-board/skills"
    "$HERMES_HOME/profiles/dua-branding/skills"
    "$HERMES_HOME/profiles/niqah/skills"
    "$HERMES_HOME/profiles/omca-development/skills"
    # AGENT-* workspaces (discovered dynamically)
)

# Discover AGENT-* workspaces
for ws in "$HOME"/Desktop/AGENT-*/.opencode/skills; do
    [ -d "$ws" ] || continue
    DESTINATIONS+=("$ws")
done

# ── helpers ───────────────────────────────────────────────────────────

log()  { printf "  %s\n" "$*"; }
say()  { printf "==> %s\n" "$*"; }
fail() { printf "FAIL: %s\n" "$*" >&2; }
note() { printf "  (skipped — %s)\n" "$*"; }

link_skill() {
    local skill="$1" dest_root="$2"
    local dest="$dest_root/$skill"
    local source="$SCRIPT_DIR/$skill"

    # Already linked correctly? Skip.
    if [ -L "$dest" ]; then
        local target
        target=$(readlink "$dest")
        if [ "$target" = "$source" ]; then
            note "already linked: $dest"
            return 0
        fi
    fi

    # Exists but is NOT a symlink to our source? Don't clobber — log + skip.
    if [ -e "$dest" ] || [ -L "$dest" ]; then
        note "exists (not ours): $dest -> $(readlink "$dest" 2>/dev/null || echo real-path)"
        return 0
    fi

    if [ "$DRY_RUN" = "1" ]; then
        log "WOULD link: $dest -> $source"
    else
        mkdir -p "$dest_root"
        ln -sfn "$source" "$dest"
        log "linked: $dest -> $source"
    fi
}

unlink_skill() {
    local skill="$1" dest_root="$2"
    local dest="$dest_root/$skill"

    if [ ! -L "$dest" ]; then
        note "not a symlink: $dest"
        return 0
    fi
    local target
    target=$(readlink "$dest")
    if [ "$target" != "$SCRIPT_DIR/$skill" ]; then
        note "not ours: $dest -> $target"
        return 0
    fi

    if [ "$DRY_RUN" = "1" ]; then
        log "WOULD unlink: $dest"
    else
        rm "$dest"
        log "unlinked: $dest"
    fi
}

# ── main ─────────────────────────────────────────────────────────────

if [ "$UNINSTALL" = "1" ]; then
    say "Uninstalling ${#SKILL_DIRS[@]} skill(s) from ${#DESTINATIONS[@]} destination(s)"
    for skill in "${SKILL_DIRS[@]}"; do
        log "[skill] $skill"
        for dest in "${DESTINATIONS[@]}"; do
            unlink_skill "$skill" "$dest"
        done
    done
    say "Done."
    exit 0
fi

say "Installing ${#SKILL_DIRS[@]} skill(s) to ${#DESTINATIONS[@]} destination(s)"
for skill in "${SKILL_DIRS[@]}"; do
    log "[skill] $skill"
    for dest in "${DESTINATIONS[@]}"; do
        link_skill "$skill" "$dest"
    done
done
say "Done. Restart Hermes gateway to pick up the new skills:"
say "  pkill -f 'hermes.*gateway run --replace' && hermes gateway run --replace &"
exit 0