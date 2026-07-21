#!/usr/bin/env bash
# sync-to-github.sh — Push the archetype-router plugin to its GitHub repo.
#
# Usage:
#   ./sync-to-github.sh           # copy + commit + push
#   ./sync-to-github.sh --dry-run # show what would be done
#
# Architecture:
#   The plugin's source of truth is ~/Desktop/OMCA-GODMODE/TOOLS/archetype-router/
#   (the OMCA monorepo). This script copies that directory into a local mirror
#   at ~/Code/hermes-archetype-subagent/ and pushes the mirror to GitHub.
#
#   The gateway's symlink (in ~/.hermes/plugins/archetype-router) keeps pointing
#   at the OMCA monorepo location. This script never touches that symlink.
#
#   To switch the gateway to use the GitHub mirror instead, manually re-point:
#       ln -sfn ~/Code/hermes-archetype-subagent ~/.hermes/plugins/archetype-router

set -euo pipefail

SOURCE="${ARCHETYPE_SOURCE:-$HOME/Desktop/OMCA-GODMODE/TOOLS/archetype-router}"
MIRROR="${ARCHETYPE_MIRROR:-$HOME/Code/hermes-archetype-subagent}"
REMOTE="${ARCHETYPE_REMOTE:-origin}"
BRANCH="${ARCHETYPE_BRANCH:-main}"

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

say()    { printf "==> %s\n" "$*"; }
note()   { printf "  %s\n" "$*"; }

# ── 1. validate source ────────────────────────────────────────────────

if [ ! -d "$SOURCE" ]; then
    echo "ERROR: source dir not found: $SOURCE" >&2
    exit 1
fi
if [ ! -f "$SOURCE/plugin.yaml" ]; then
    echo "ERROR: $SOURCE doesn't look like the plugin (no plugin.yaml)" >&2
    exit 1
fi
note "Source: $SOURCE"

# ── 2. validate mirror ───────────────────────────────────────────────

if [ ! -d "$MIRROR/.git" ]; then
    echo "ERROR: mirror not a git repo: $MIRROR" >&2
    echo "       (run the bootstrap step: git init + gh repo create)" >&2
    exit 1
fi
note "Mirror: $MIRROR"

# ── 3. rsync source -> mirror (excluding runtime/test artifacts) ──

if [ "$DRY_RUN" = "1" ]; then
    say "Dry run — would rsync:"
    rsync -avhn --delete \
        --exclude='.git' \
        --exclude='.coverage' \
        --exclude='.coverage.*' \
        --exclude='.pytest_cache' \
        --exclude='__pycache__' \
        --exclude='.venv' \
        --exclude='uv.lock' \
        "$SOURCE/" "$MIRROR/" 2>&1 | tail -5
else
    say "Syncing source -> mirror..."
    rsync -a --delete \
        --exclude='.git' \
        --exclude='.coverage' \
        --exclude='.coverage.*' \
        --exclude='.pytest_cache' \
        --exclude='__pycache__' \
        --exclude='.venv' \
        --exclude='uv.lock' \
        "$SOURCE/" "$MIRROR/"
    note "rsync done"
fi

# ── 4. commit changes in mirror ──────────────────────────────────────

if [ "$DRY_RUN" = "1" ]; then
    say "Dry run — would commit (if there are changes):"
    if ! (cd "$MIRROR" && git diff --quiet) 2>/dev/null; then
        (cd "$MIRROR" && git diff --stat | head -5)
    else
        note "(no changes)"
    fi
else
    if (cd "$MIRROR" && git diff --quiet HEAD) 2>/dev/null && (cd "$MIRROR" && git diff --cached --quiet) 2>/dev/null; then
        note "No changes to commit"
    else
        say "Committing changes..."
        (cd "$MIRROR" && git add -A)
        # Auto-generate commit message: list changed files + diff stat
        if (cd "$MIRROR" && git diff --cached --quiet); then
            note "(nothing to commit after all)"
        else
            changed=$(cd "$MIRROR" && git diff --cached --name-only | wc -l | tr -d ' ')
            msg="sync: $changed file(s) from OMCA monorepo

$(cd "$MIRROR" && git diff --cached --stat | head -20)"
            (cd "$MIRROR" && git commit -m "$msg" 2>&1 | tail -5)
        fi
    fi
fi

# ── 5. push to remote ───────────────────────────────────────────────

if [ "$DRY_RUN" = "1" ]; then
    say "Dry run — would push to $REMOTE/$BRANCH:"
    (cd "$MIRROR" && git log --oneline origin/$BRANCH..HEAD 2>/dev/null | head -5) || note "(no commits ahead of origin)"
else
    ahead=$(cd "$MIRROR" && git rev-list --count origin/$BRANCH..HEAD 2>/dev/null || echo 0)
    if [ "$ahead" = "0" ]; then
        note "Nothing to push (mirror is up to date with origin/$BRANCH)"
    else
        say "Pushing $ahead commit(s) to $REMOTE/$BRANCH..."
        (cd "$MIRROR" && git push "$REMOTE" "$BRANCH" 2>&1 | tail -5)
    fi
fi

say "Done."