#!/usr/bin/env bash
set -euo pipefail

# Clean up browser automation and test artifacts that can accumulate in the
# repository root. Only targets known artifact patterns at the root level;
# does not recurse into subdirectories. Safe to run at any time.
#
# Usage:
#   ./scripts/clean_browser_artifacts.sh          # real removal
#   ./scripts/clean_browser_artifacts.sh --dry-run  # preview only

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN=false

case "${1:-}" in
    --dry-run) DRY_RUN=true ;;
    -h|--help)
        echo "Usage: $(basename "$0") [--dry-run]"
        echo "Remove browser/test artifacts from the repository root."
        exit 0
        ;;
esac

ARTIFACT_PATTERNS=(
    ".playwright-mcp"
    "*.png"
    "*.jpg"
    "*.jpeg"
    "*.webp"
    "*.webm"
    "playwright-report"
    "test-results"
    "screenshots"
    "debug-screenshots"
)

REMOVED=0
for pattern in "${ARTIFACT_PATTERNS[@]}"; do
    while IFS= read -r -d '' entry; do
        if $DRY_RUN; then
            echo "[dry-run] would remove: ${entry#$REPO_ROOT/}"
        else
            rm -rf "$entry"
            echo "[removed] ${entry#$REPO_ROOT/}"
        fi
        ((REMOVED++))
    done < <(find "$REPO_ROOT" -maxdepth 1 -name "$pattern" -print0 2>/dev/null || true)
done

if $DRY_RUN; then
    echo "[clean_browser_artifacts] Dry-run: $REMOVED artifact(s) would be removed from repository root."
else
    echo "[clean_browser_artifacts] Removed $REMOVED artifact(s) from repository root."
fi
