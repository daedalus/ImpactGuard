#!/usr/bin/env bash
set -euo pipefail

# ── release.sh ──────────────────────────────────────────────────────────────
# Bump version → commit + tag → push → build → GitHub release.
# Usage:  ./release.sh [patch|minor|major]   (default: patch)
# ────────────────────────────────────────────────────────────────────────────

PART="${1:-patch}"

# Ensure working tree is clean
if ! git diff --stat --exit-code; then
    echo "error: working tree has uncommitted changes; aborting." >&2
    exit 1
fi

# Ensure we are on master (or main)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "master" ] && [ "$BRANCH" != "main" ]; then
    echo "warning: releasing from branch '$BRANCH' (not master/main)"
fi

echo "==> bumpversion $PART"
rtk bumpversion "$PART" --tag --verbose

echo "==> push commit + tags"
rtk git push
rtk git push --tags

echo "==> build"
rtk python -m build

echo "==> gh release"
# Grab the new version from the tag we just pushed
TAG=$(git describe --tags --abbrev=0)
rtk gh release create "$TAG" --generate-notes

echo "==> done: $TAG released"
