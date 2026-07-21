#!/usr/bin/env bash
# install.sh — Install bundled skills to Hermes root and all profiles.
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

if [ ! -d "$HERMES_HOME" ]; then
    echo "Error: Hermes home directory not found at $HERMES_HOME" >&2
    exit 1
fi

# Discover skills in SCRIPT_DIR
SKILL_DIRS=()
for dir in "$SCRIPT_DIR"/*/; do
    [ -d "$dir" ] || continue
    [ -f "$dir/SKILL.md" ] || continue
    SKILL_DIRS+=("$(basename "$dir")")
done

if [ ${#SKILL_DIRS[@]} -eq 0 ]; then
    echo "No skills found in $SCRIPT_DIR" >&2
    exit 1
fi

echo "Found skills to install: ${SKILL_DIRS[*]}"

# Build list of destinations
DESTINATIONS=("$HERMES_HOME/skills")

if [ -d "$HERMES_HOME/profiles" ]; then
    for pdir in "$HERMES_HOME/profiles"/*; do
        if [ -d "$pdir" ]; then
            DESTINATIONS+=("$pdir/skills")
        fi
    done
fi

for dest in "${DESTINATIONS[@]}"; do
    echo "Installing to $dest..."
    mkdir -p "$dest"
    for skill in "${SKILL_DIRS[@]}"; do
        # Clean up existing file/link/dir at destination to avoid nesting/conflicts
        rm -rf "$dest/$skill"
        cp -R "$SCRIPT_DIR/$skill" "$dest/"
        echo "  copied $skill"
    done
done

echo "Done! Restart Hermes gateway to load the new skills."
