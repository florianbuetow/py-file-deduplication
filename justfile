# Default recipe: show available commands
_default:
    @clear
    @printf "\n"
    @just --list --unsorted
    @printf "\n"

# Scan configured directories and populate the database with file entries
[group('app')]
scan:
    @printf "\n"
    @printf "\033[0;34m=== Scanning Files ===\033[0m\n"
    @uv run src/scan.py
    @printf "\n"

# Compute MD5 and SHA-256 hashes for all unhashed files in the database
[group('app')]
hash:
    @printf "\n"
    @printf "\033[0;34m=== Hashing Files ===\033[0m\n"
    @uv run src/hash.py
    @printf "\n"

# Check all database entries against disk and remove missing files
[group('app')]
scan-update:
    @printf "\n"
    @printf "\033[0;34m=== Scan Update ===\033[0m\n"
    @uv run src/scan_update.py
    @printf "\n"

# Find duplicate files in the database by comparing hashes
[group('app')]
duplicates:
    @printf "\n"
    @printf "\033[0;34m=== Finding Duplicates ===\033[0m\n"
    @uv run src/duplicates.py
    @printf "\n"

# Interactively select and remove duplicate files by folder
[group('app')]
cleanup:
    @printf "\n"
    @printf "\033[0;34m=== Cleanup Duplicates ===\033[0m\n"
    @uv run src/cleanup.py
    @printf "\n"

# Delete the database (requires typing 'destroy' to confirm)
[group('app')]
reset:
    @printf "\n"
    @printf "\033[0;31m=== Database Reset ===\033[0m\n"
    @printf "\n"
    @./scripts/reset-db.sh
    @printf "\n"

# Show help information
[group('info')]
help:
    @printf "\n"
    @clear
    @printf "\n"
    @printf "\033[0;34m=== raw-deduplicator_v2 ===\033[0m\n"
    @printf "\n"
    @printf "Available commands:\n"
    @just --list --unsorted
    @printf "\n"

# Generate code statistics with pygount
[group('info')]
code-stats:
    @printf "\n"
    @printf "\033[0;34m=== Code Statistics ===\033[0m\n"
    @mkdir -p reports
    @uv run pygount src/ tests/ scripts/ prompts/ *.md *.toml --suffix=py,md,txt,toml,yaml,yml --format=summary
    @printf "\n"
    @uv run pygount src/ tests/ scripts/ prompts/ *.md *.toml --suffix=py,md,txt,toml,yaml,yml --format=summary > reports/code-stats.txt
    @printf "\033[0;32m✓ Report saved to reports/code-stats.txt\033[0m\n"
    @printf "\n"

# Initialize the development environment
[group('setup')]
init:
    @printf "\n"
    @printf "\033[0;34m=== Initializing Development Environment ===\033[0m\n"
    @mkdir -p reports/coverage
    @mkdir -p reports/security
    @mkdir -p reports/pyright
    @mkdir -p reports/deptry
    @printf "Installing Python dependencies...\n"
    @uv sync --all-extras
    @printf "\033[0;32m✓ Development environment ready\033[0m\n"
    @printf "\n"

# Destroy the virtual environment
[group('setup')]
destroy:
    @printf "\n"
    @printf "\033[0;34m=== Destroying Virtual Environment ===\033[0m\n"
    @rm -rf .venv
    @printf "\033[0;32m✓ Virtual environment removed\033[0m\n"
    @printf "\n"

# Auto-fix code style and formatting
[group('quality')]
code-format:
    @printf "\n"
    @printf "\033[0;34m=== Formatting Code ===\033[0m\n"
    @uv run ruff check . --fix
    @printf "\n"
    @uv run ruff format .
    @printf "\n"
    @printf "\033[0;32m✓ Code formatted\033[0m\n"
    @printf "\n"

# Check code style and formatting (read-only)
[group('quality')]
code-style:
    @printf "\n"
    @printf "\033[0;34m=== Checking Code Style ===\033[0m\n"
    @uv run ruff check .
    @printf "\n"
    @uv run ruff format --check .
    @printf "\n"
    @printf "\033[0;32m✓ Style checks passed\033[0m\n"
    @printf "\n"

# Run static type checking with mypy
[group('quality')]
code-typecheck:
    @printf "\n"
    @printf "\033[0;34m=== Running Type Checks ===\033[0m\n"
    @uv run mypy src/
    @printf "\n"
    @printf "\033[0;32m✓ Type checks passed\033[0m\n"
    @printf "\n"

# Run strict type checking with Pyright (LSP-based)
[group('quality')]
code-lspchecks:
    @printf "\n"
    @printf "\033[0;34m=== Running Pyright Type Checks ===\033[0m\n"
    @mkdir -p reports/pyright
    @uv run pyright --project pyrightconfig.json > reports/pyright/pyright.txt 2>&1 || true
    @uv run pyright --project pyrightconfig.json
    @printf "\n"
    @printf "\033[0;32m✓ Pyright checks passed\033[0m\n"
    @printf "  Report: reports/pyright/pyright.txt\n"
    @printf "\n"

# Run security checks with bandit
[group('quality')]
code-security:
    @printf "\n"
    @printf "\033[0;34m=== Running Security Checks ===\033[0m\n"
    @mkdir -p reports/security
    @uv run bandit -c pyproject.toml -r src -f txt -o reports/security/bandit.txt || true
    @uv run bandit -c pyproject.toml -r src
    @printf "\n"
    @printf "\033[0;32m✓ Security checks passed\033[0m\n"
    @printf "\n"

# Check dependency hygiene with deptry
[group('quality')]
code-deptry:
    @printf "\n"
    @printf "\033[0;34m=== Checking Dependencies ===\033[0m\n"
    @mkdir -p reports/deptry
    @uv run deptry src
    @printf "\n"
    @printf "\033[0;32m✓ Dependency checks passed\033[0m\n"
    @printf "\n"

# Check spelling in code and documentation
[group('quality')]
code-spell:
    @printf "\n"
    @printf "\033[0;34m=== Checking Spelling ===\033[0m\n"
    @uv run codespell src tests scripts prompts *.md *.toml
    @printf "\n"
    @printf "\033[0;32m✓ Spelling checks passed\033[0m\n"
    @printf "\n"

# Run Semgrep static analysis
[group('quality')]
code-semgrep:
    @printf "\n"
    @printf "\033[0;34m=== Running Semgrep Static Analysis ===\033[0m\n"
    @uv run semgrep --config config/semgrep/ --error src
    @printf "\n"
    @printf "\033[0;32m✓ Semgrep checks passed\033[0m\n"
    @printf "\n"

# Scan dependencies for known vulnerabilities
[group('quality')]
code-audit:
    @printf "\n"
    @printf "\033[0;34m=== Scanning Dependencies for Vulnerabilities ===\033[0m\n"
    @uv run pip-audit
    @printf "\n"
    @printf "\033[0;32m✓ No known vulnerabilities found\033[0m\n"
    @printf "\n"

# Run unit tests only (fast)
[group('test')]
test:
    @printf "\n"
    @printf "\033[0;34m=== Running Unit Tests ===\033[0m\n"
    @uv run pytest tests/ -v
    @printf "\n"

# Run TUI integration test for cleanup expand/collapse (requires tmux)
[group('test')]
test-tui:
    @printf "\n"
    @printf "\033[0;34m=== TUI Integration Test ===\033[0m\n"
    @./scripts/test_cleanup_tui.sh
    @printf "\n"

# Run unit tests with coverage report and threshold check
[group('test')]
test-coverage: init
    @printf "\n"
    @printf "\033[0;34m=== Running Unit Tests with Coverage ===\033[0m\n"
    @uv run pytest tests/ -v \
        --cov=src \
        --cov-report=html:reports/coverage/html \
        --cov-report=term \
        --cov-report=xml:reports/coverage/coverage.xml \
        --cov-fail-under=80
    @printf "\n"
    @printf "\033[0;32m✓ Coverage threshold met\033[0m\n"
    @printf "  HTML: reports/coverage/html/index.html\n"
    @printf "\n"

# Run ALL validation checks (verbose)
[group('ci')]
ci:
    #!/usr/bin/env bash
    set -e
    printf "\n"
    printf "\033[0;34m=== Running CI Checks ===\033[0m\n"
    printf "\n"
    just init
    just code-format
    just code-style
    just code-typecheck
    just code-security
    just code-deptry
    just code-spell
    just code-semgrep
    just code-audit
    just test
    just code-lspchecks
    printf "\n"
    printf "\033[0;32m✓ All CI checks passed\033[0m\n"
    printf "\n"

# Run ALL validation checks silently (only show output on errors)
[group('ci')]
ci-quiet:
    #!/usr/bin/env bash
    set -e
    printf "\n"
    printf "\033[0;34m=== Running CI Checks (Quiet Mode) ===\033[0m\n"
    TMPFILE=$(mktemp)
    trap "rm -f $TMPFILE" EXIT

    just init > $TMPFILE 2>&1 || { printf "\033[0;31m✗ Init failed\033[0m\n"; cat $TMPFILE; exit 1; }
    printf "\033[0;32m✓ Init passed\033[0m\n"

    just code-format > $TMPFILE 2>&1 || { printf "\033[0;31m✗ Code-format failed\033[0m\n"; cat $TMPFILE; exit 1; }
    printf "\033[0;32m✓ Code-format passed\033[0m\n"

    just code-style > $TMPFILE 2>&1 || { printf "\033[0;31m✗ Code-style failed\033[0m\n"; cat $TMPFILE; exit 1; }
    printf "\033[0;32m✓ Code-style passed\033[0m\n"

    just code-typecheck > $TMPFILE 2>&1 || { printf "\033[0;31m✗ Code-typecheck failed\033[0m\n"; cat $TMPFILE; exit 1; }
    printf "\033[0;32m✓ Code-typecheck passed\033[0m\n"

    just code-security > $TMPFILE 2>&1 || { printf "\033[0;31m✗ Code-security failed\033[0m\n"; cat $TMPFILE; exit 1; }
    printf "\033[0;32m✓ Code-security passed\033[0m\n"

    just code-deptry > $TMPFILE 2>&1 || { printf "\033[0;31m✗ Code-deptry failed\033[0m\n"; cat $TMPFILE; exit 1; }
    printf "\033[0;32m✓ Code-deptry passed\033[0m\n"

    just code-spell > $TMPFILE 2>&1 || { printf "\033[0;31m✗ Code-spell failed\033[0m\n"; cat $TMPFILE; exit 1; }
    printf "\033[0;32m✓ Code-spell passed\033[0m\n"

    just code-semgrep > $TMPFILE 2>&1 || { printf "\033[0;31m✗ Code-semgrep failed\033[0m\n"; cat $TMPFILE; exit 1; }
    printf "\033[0;32m✓ Code-semgrep passed\033[0m\n"

    just code-audit > $TMPFILE 2>&1 || { printf "\033[0;31m✗ Code-audit failed\033[0m\n"; cat $TMPFILE; exit 1; }
    printf "\033[0;32m✓ Code-audit passed\033[0m\n"

    just test > $TMPFILE 2>&1 || { printf "\033[0;31m✗ Test failed\033[0m\n"; cat $TMPFILE; exit 1; }
    printf "\033[0;32m✓ Test passed\033[0m\n"

    just code-lspchecks > $TMPFILE 2>&1 || { printf "\033[0;31m✗ Code-lspchecks failed\033[0m\n"; cat $TMPFILE; exit 1; }
    printf "\033[0;32m✓ Code-lspchecks passed\033[0m\n"

    printf "\n"
    printf "\033[0;32m✓ All CI checks passed\033[0m\n"
    printf "\n"
