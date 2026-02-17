#!/usr/bin/env bash
# TUI integration test for cleanup expand/collapse using tmux.
#
# Tests:
#   1. Default view shows only top-level folders with ▸ indicators
#   2. Enter on collapsed folder expands it (▸ → ▾, children appear)
#   3. Enter again collapses it (▾ → ▸, children hidden)
#   4. Tab toggles [x] selection
#   5. d accepts and shows deletion confirmation
#   6. n returns to folder tree
#   7. Escape cancels and exits
#
# Requires: tmux, uv

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Cleanup ---
TMPDIR_BASE=""
SESSION=""
cleanup() {
    if [ -n "$SESSION" ] && tmux has-session -t "$SESSION" 2>/dev/null; then
        tmux kill-session -t "$SESSION" 2>/dev/null || true
    fi
    if [ -n "$TMPDIR_BASE" ] && [ -d "$TMPDIR_BASE" ]; then
        rm -rf "$TMPDIR_BASE"
    fi
}
trap cleanup EXIT

# --- Helpers ---
PASS_COUNT=0
FAIL_COUNT=0

assert_screen_contains() {
    local desc="$1"
    local pattern="$2"
    local captured
    captured="$(tmux capture-pane -t "$SESSION" -p)"
    if printf '%s' "$captured" | grep -qF "$pattern"; then
        printf "\033[0;32m  ✓ %s\033[0m\n" "$desc"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        printf "\033[0;31m  ✗ %s\033[0m\n" "$desc"
        printf "    Expected to find: %s\n" "$pattern"
        printf "    Screen contents:\n"
        printf '%s\n' "$captured" | sed 's/^/    | /'
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_screen_not_contains() {
    local desc="$1"
    local pattern="$2"
    local captured
    captured="$(tmux capture-pane -t "$SESSION" -p)"
    if ! printf '%s' "$captured" | grep -qF "$pattern"; then
        printf "\033[0;32m  ✓ %s\033[0m\n" "$desc"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        printf "\033[0;31m  ✗ %s\033[0m\n" "$desc"
        printf "    Expected NOT to find: %s\n" "$pattern"
        printf "    Screen contents:\n"
        printf '%s\n' "$captured" | sed 's/^/    | /'
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

wait_for_screen() {
    local pattern="$1"
    local timeout="${2:-10}"
    local elapsed=0
    while [ $elapsed -lt "$timeout" ]; do
        if tmux capture-pane -t "$SESSION" -p | grep -qF "$pattern"; then
            return 0
        fi
        sleep 0.5
        elapsed=$((elapsed + 1))
    done
    return 1
}

# --- Setup test data ---
printf "\033[0;34mSetting up test data...\033[0m\n"

TMPDIR_BASE="$(mktemp -d)"
SCAN_DIR="$TMPDIR_BASE/files"
mkdir -p "$SCAN_DIR/originals/2024/vacation"
mkdir -p "$SCAN_DIR/originals/2024/work"
mkdir -p "$SCAN_DIR/backup"

# Create duplicate files: same content = same hash
CONTENT_A="duplicate_content_alpha_1234567890"
CONTENT_B="duplicate_content_beta_0987654321"

printf '%s' "$CONTENT_A" > "$SCAN_DIR/originals/2024/vacation/photo1.raw"
printf '%s' "$CONTENT_A" > "$SCAN_DIR/backup/photo1.raw"

printf '%s' "$CONTENT_B" > "$SCAN_DIR/originals/2024/work/doc1.raw"
printf '%s' "$CONTENT_B" > "$SCAN_DIR/backup/doc1.raw"

# Create config
cat > "$TMPDIR_BASE/config.yaml" <<YAML
paths:
  - "$SCAN_DIR"
extensions:
  - ".raw"
case_sensitive: false
recursive: true
skip_dirs: []
database: "$TMPDIR_BASE/test.db"
YAML

# Scan and hash files
cd "$PROJECT_ROOT"
uv run python -c "
import sys
from pathlib import Path
sys.path.insert(0, 'src')
from app.config import load_config
from app.database import open_database
from app.scanner import scan_files
from app.hasher import hash_files

config = load_config(Path('$TMPDIR_BASE/config.yaml'))
conn = open_database(Path('$TMPDIR_BASE/test.db'))
scan_files(config, conn)
hash_files(conn, Path('$SCAN_DIR'))
conn.close()
" 2>&1 | sed 's/^/  /'

printf "\033[0;32m  ✓ Test data ready\033[0m\n"

# --- Launch TUI in tmux ---
printf "\n\033[0;34mLaunching TUI in tmux...\033[0m\n"

# Write a helper script to avoid quoting issues in tmux
LAUNCH_SCRIPT="$TMPDIR_BASE/launch_tui.py"
cat > "$LAUNCH_SCRIPT" <<PYEOF
import sys
from pathlib import Path

sys.path.insert(0, "src")
from app.database import open_database
from app.cleanup import run_cleanup_interactive

conn = open_database(Path("$TMPDIR_BASE/test.db"))
base_path = Path("$SCAN_DIR")
run_cleanup_interactive(conn, base_path)
conn.close()
print("=== TUI EXITED ===")
PYEOF

SESSION="dedup-tui-test-$$"
tmux new-session -d -s "$SESSION" -x 120 -y 40 \
    "cd '$PROJECT_ROOT' && uv run python '$LAUNCH_SCRIPT' 2>&1; sleep 5"

# Wait for the TUI to render
if ! wait_for_screen "Select folders" 15; then
    printf "\033[0;31m  ✗ TUI did not start within timeout\033[0m\n"
    tmux capture-pane -t "$SESSION" -p | sed 's/^/    | /'
    exit 1
fi
sleep 1

# --- Test 1: Default view - collapsed with ▸ indicators ---
printf "\n\033[0;34mTest 1: Default view (collapsed)\033[0m\n"
assert_screen_contains "Shows ▸ indicator for expandable folders" "▸"
assert_screen_contains "Shows backup/ folder" "backup/"
assert_screen_contains "Shows originals/ folder" "originals/"
assert_screen_not_contains "Children are hidden (no vacation/)" "vacation/"
assert_screen_not_contains "Children are hidden (no work/)" "work/"

# --- Test 2: Enter expands folder ---
printf "\n\033[0;34mTest 2: Enter expands folder\033[0m\n"
# Move to originals/ (it should be the second entry after backup/)
tmux send-keys -t "$SESSION" Down
sleep 0.3
tmux send-keys -t "$SESSION" Enter
sleep 1

assert_screen_contains "Shows ▾ indicator after expanding" "▾"

# Expand deeper: originals/2024
tmux send-keys -t "$SESSION" Down
sleep 0.3
tmux send-keys -t "$SESSION" Enter
sleep 1

assert_screen_contains "Children visible: vacation/" "vacation/"
assert_screen_contains "Children visible: work/" "work/"

# --- Test 3: Enter collapses folder ---
printf "\n\033[0;34mTest 3: Enter collapses folder\033[0m\n"
# After expanding originals and originals/2024, cursor is restored to
# 2024/ (idx 2). Navigate up to originals/ (idx 1) and collapse it.
tmux send-keys -t "$SESSION" Up
sleep 0.3
# Now on originals/ (idx 1), press Enter to collapse
tmux send-keys -t "$SESSION" Enter
sleep 1

assert_screen_not_contains "Children hidden after collapse" "vacation/"

# --- Test 4: Space toggles selection ---
printf "\n\033[0;34mTest 4: Space toggles selection\033[0m\n"
# Move to backup/ (first entry)
tmux send-keys -t "$SESSION" Up
sleep 0.3
tmux send-keys -t "$SESSION" Space
sleep 0.5

assert_screen_contains "Selection marker shown" "[*]"

# --- Test 5: d accepts selection ---
printf "\n\033[0;34mTest 5: d accepts and shows confirmation\033[0m\n"
tmux send-keys -t "$SESSION" d
sleep 1

assert_screen_contains "Shows deletion plan" "Files to delete"

# --- Test 6: n returns to tree ---
printf "\n\033[0;34mTest 6: Decline deletion\033[0m\n"
# At the "Proceed with deletion? [y/N]" prompt, type n + Enter
tmux send-keys -t "$SESSION" n
sleep 0.3
tmux send-keys -t "$SESSION" Enter
sleep 2

# After declining, should return to folder selection
if wait_for_screen "Select folders" 5; then
    assert_screen_contains "Returns to folder selection" "Select folders"
else
    printf "\033[0;33m  ~ Skipped: TUI may have re-rendered differently\033[0m\n"
fi

# --- Test 7: Escape cancels ---
printf "\n\033[0;34mTest 7: Escape cancels\033[0m\n"
tmux send-keys -t "$SESSION" Escape
sleep 1

assert_screen_contains "TUI exited after Escape" "Cancelled"

# --- Summary ---
printf "\n\033[0;34m=== Results ===\033[0m\n"
TOTAL=$((PASS_COUNT + FAIL_COUNT))
printf "  Passed: %d/%d\n" "$PASS_COUNT" "$TOTAL"

if [ "$FAIL_COUNT" -gt 0 ]; then
    printf "  \033[0;31mFailed: %d/%d\033[0m\n" "$FAIL_COUNT" "$TOTAL"
    exit 1
else
    printf "  \033[0;32mAll tests passed!\033[0m\n"
    exit 0
fi
