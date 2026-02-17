# py-file-deduplication

A Python CLI tool for finding and removing duplicate files across large directory trees. Designed for managing terabytes of data across multiple drives and backups.

## What It Does

You configure which directories and file extensions to scan, then run a pipeline of commands that build on each other:

**Configure** -- Define your scan directories, file extensions, and database location in a single YAML file. All settings are explicit, nothing is assumed.

**Scan** -- Crawl directories and record every matching file into a SQLite database. Re-running scan adds new files and removes entries for files that no longer exist on disk.

**Hash** -- Compute MD5 + SHA-256 hashes for every file. Dual hashes eliminate false positives. Only unhashed files are processed, so you can interrupt and resume at any time.

**Report** -- Show duplicate groups, how many copies exist, and total reclaimable disk space.

**Clean up** -- Interactive terminal menu ranks folders by duplicate count. Select which folders to clean, review a dry-run report showing exactly what will be deleted and where surviving copies live, then confirm. The tool never deletes the last copy of any file -- if all folders containing a file are selected, the alphabetically first copy is automatically protected.

## Pipeline

```
configure  -->  scan  -->  hash  -->  report  -->  cleanup
```

Each stage is a separate command. You can inspect results between steps and re-run any stage safely.

## Key Properties

- **Incremental** -- Scan detects new and removed files. Hash only processes files that haven't been hashed yet. No wasted work on re-runs.
- **Safe deletion** -- Last-copy protection guarantees at least one copy of every file is always preserved. Dry-run report before any file is touched.
- **Resumable** -- Hashing large volumes can take hours. Interrupt and resume without losing progress.
- **Dual-hash verification** -- Files are matched by size + MD5 + SHA-256. False positives are effectively impossible.
- **Configuration-driven** -- Works with any file type. Extensions, directories, and exclusions are all configured in YAML.

## Usage

### Configuration

Create a `config.yaml` in your project root:

```yaml
paths:
  - "/Volumes/Photos"

extensions:
  - ".CR3"
  - ".ARW"
  - ".DNG"
  - ".JPG"

case_sensitive: false
recursive: true

skip_dirs:
  - ".git"
  - "__pycache__"
  - "_DELETE"

database: "data/files.db"
```

All fields are required.

### Commands

```bash
just scan          # Scan directories, add new files, remove stale entries
just hash          # Compute hashes for unhashed files
just duplicates    # Report duplicate groups and reclaimable space
just cleanup       # Interactive folder-based duplicate removal
just reset         # Delete the database (requires confirmation)
```

### Interactive Cleanup

`just cleanup` presents folders ranked by duplicate count:

```
Select folders to remove duplicates from (Space to toggle, Enter to confirm):
[ ] trip-backup/photos/     (247 duplicates, 12.50 GB)
[ ] old-drive/raw/          (183 duplicates, 8.30 GB)
[ ] copies/2024/            ( 42 duplicates, 1.70 GB)
```

After selecting, a dry-run report shows what will happen:

```
Files to delete (2 folders selected):

  trip-backup/photos/IMG_001.CR3  (25.50 MB)  -- kept in: raw/2024/IMG_001.CR3
  trip-backup/photos/IMG_002.CR3  (25.10 MB)  -- kept in: raw/2024/IMG_002.CR3
  ...

  Total: 247 files, 12.50 GB

Proceed with deletion? [y/N]
```

Nothing is deleted until you type `y`.

## Getting Started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) -- Python package manager
- [just](https://github.com/casey/just#installation) -- command runner

### Setup

```bash
just init
```

## Development

### Code Quality

```bash
just ci          # Run all 11 validation checks (verbose)
just ci-quiet    # Same, but silent unless something fails
```

The CI pipeline includes: formatting and linting (ruff), type checking (mypy + pyright), security scanning (bandit + semgrep), dependency auditing, and spell checking.

### Testing

```bash
just test            # Run all tests
just test-coverage   # Run with coverage report
```

The test suite includes unit tests for every module and end-to-end tests that create real files on disk, run the full scan/hash/cleanup pipeline, and verify both disk and database state after deletion.

### Project Structure

```
src/
  app/
    cleanup.py       # Folder analysis, deletion planning, TUI, execution
    cli.py           # CLI entry points
    config.py        # YAML configuration loading and validation
    database.py      # SQLite operations
    duplicates.py    # Duplicate group reporting
    hasher.py        # MD5 + SHA-256 hashing with progress
    scan_updater.py  # Stale entry detection
    scanner.py       # Directory crawling and file discovery
tests/
  test_cleanup.py       # Cleanup unit tests
  test_cleanup_e2e.py   # End-to-end tests with real files
  test_config.py        # Config loading tests
  test_database.py      # Database operation tests
  test_hasher.py        # Hasher tests
  test_scanner.py       # Scanner tests
```
