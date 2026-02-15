# Development Rules for raw-deduplicator_v2

This file provides guidance to AI agents and AI-assisted development tools when working with this project. This includes Claude Code, Cursor IDE, GitHub Copilot, Windsurf, and any other AI coding assistants.

## General Coding Principles
- **Never assume any default values anywhere**
- Always be explicit about values, paths, and configurations
- If a value is not provided, handle it explicitly (raise error, use null, or prompt for input)

## Git Commit Guidelines

**IMPORTANT:** When creating git commits in this repository:
- **NEVER include AI attribution in commit messages**
- **NEVER add "Generated with [AI tool name]" or similar phrases**
- **NEVER add "Co-Authored-By: [AI name]" or similar attribution**
- **NEVER run `git add -A` or `git add .` - always stage files explicitly**
- Keep commit messages professional and focused on the changes made
- Commit messages should describe what changed and why, without mentioning AI assistance
- **ALWAYS run `git push` after creating a commit to push changes to the remote repository**

## Testing
- After **every change** to the code, the tests must be executed
- Always verify the program runs correctly after modifications
- **Always use justfile targets** for testing and running: `just test`, `just scan`, `just hash`, etc.
- Prefer `just ci` or `just ci-quiet` for full validation over running individual tools manually

## Python Execution Rules
- Python code must be executed **only** via `uv run ...`
  - Example: `uv run src/scan.py`
  - **Never** use: `python src/main.py` or `python3 src/main.py`
- The virtual environment must be created and updated **only** via `uv sync`
  - **Never** use: `pip install`, `python -m pip`, or `uv pip`
- All dependencies must be managed through `uv` and declared in `pyproject.toml`

## Shell Script Rules
- **Always use `printf` instead of `echo` for colored output** - `echo` does not reliably interpret ANSI escape sequences across shells
  - Wrong: `echo "\033[0;32m✓ Done\033[0m"`
  - Correct: `printf "\033[0;32m✓ Done\033[0m\n"`
- **Never run scripts with the `bash` prefix** — always `chmod +x` the script and execute it directly
  - Wrong: `bash scripts/reset-db.sh`
  - Correct: `chmod +x scripts/reset-db.sh` then `./scripts/reset-db.sh`

## Justfile Rules
- **Every justfile recipe must start with `@printf "\n"` and end with `@printf "\n"`** to ensure clean visual separation between targets in terminal output
- All Python execution in the justfile uses `uv run`, never `python` directly
- **Never inline Python code in the justfile** — if logic is needed, write a helper script in `scripts/` and call it from the recipe
- **Never inline complex bash logic in the justfile** — keep recipes as thin runners that delegate to scripts in `scripts/`
- **All helper scripts (bash or Python) go in `scripts/`** — never place them in the project root or other directories
- **Always use `just <target>` to run tasks** — never run `scripts/*.sh` or `scripts/*.py` directly
- Use `just init` to set up the project
- Use `just scan` to scan directories and populate the database
- Use `just hash` to compute hashes for unhashed files
- Use `just destroy` to remove the virtual environment
- Use `just help` to see all available recipes with descriptions
- Use `just` (with no arguments) to see a list of all recipes
- Use `just ci` to run all validation checks (verbose)
- Use `just ci-quiet` to run all validation checks (silent, fail-fast)

## Project Structure
- All source code lives in `src/`
- Test scripts and utilities go in `scripts/`
- Prompt templates go in `prompts/`
- **Input data is organized**: `data/input/`
- **Output data is organized**: `data/output/`
- **Never create Python files in the project root directory**
  - Wrong: `./test.py`, `./helper.py`
  - Correct: `./src/helper.py`, `./scripts/test.py`

## Error Handling
- Scripts should continue processing other items even if one fails
- Failed/invalid outputs should be handled gracefully
- Scripts should track and report success/failure counts
- Exit with code 1 if any items failed, 0 if all succeeded

## Optimization
- **Skip processing if output already exists** - Don't reprocess unnecessarily
- Check if output file exists before starting expensive operations
- Track skipped items separately in summary reports
- Allow users to force reprocessing by deleting output files
