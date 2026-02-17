# py-file-deduplication

A Python CLI tool for finding and removing duplicate files across large directory trees. Designed for managing terabytes of data across multiple drives and backups.

## What It Does

You configure which directories and file extensions to scan, then run a pipeline of commands that build on each other:

**Configure** -- Define your scan directories, file extensions, and database location in a single YAML file. All settings are explicit, nothing is assumed.

**Scan** -- Crawl directories and record every matching file into a SQLite database. Re-running scan adds new files and removes entries for files that no longer exist on disk.

**Hash** -- Compute MD5 + SHA-256 hashes for every file. Dual hashes eliminate false positives. Only unhashed files are processed, so you can interrupt and resume at any time.

**Report** -- Show duplicate groups, how many copies exist, and total reclaimable disk space.

**Clean up** -- Interactive terminal menu ranks folders by duplicate count. Select which folders to clean, review a dry-run report showing exactly what will be deleted and where surviving copies live, then confirm. The tool never deletes the last copy of any file -- if all folders containing a file are selected, the alphabetically first copy is automatically protected.

### Pipeline

```
configure  -->  scan  -->  hash  -->  report  -->  cleanup
```

Each stage is a separate command. You can inspect results between steps and re-run any stage safely.

### Key Properties

- **Incremental** -- Scan detects new and removed files. Hash only processes files that haven't been hashed yet. No wasted work on re-runs.
- **Safe deletion** -- Last-copy protection guarantees at least one copy of every file is always preserved. Dry-run report before any file is touched.
- **Resumable** -- Hashing large volumes can take hours. Interrupt and resume without losing progress.
- **Dual-hash verification** -- Files are matched by size + MD5 + SHA-256. False positives are effectively impossible.
- **Configuration-driven** -- Works with any file type. Extensions, directories, and exclusions are all configured in YAML.

## Installation

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) -- Python package manager
- [just](https://github.com/casey/just#installation) -- command runner

### Setup

```bash
git clone https://github.com/youruser/py-file-deduplication.git
cd py-file-deduplication
just init
```

## Configuration

Create a `config.yaml` in the project root. All fields are required -- the tool does not assume any defaults.

```yaml
# Directories to scan (absolute paths)
paths:
  - "/Volumes/Photos"

# File extensions to match (must include the dot)
extensions:
  - ".CR3"
  - ".ARW"
  - ".DNG"
  - ".JPG"

# Whether extension matching is case sensitive
case_sensitive: false

# Whether to crawl subdirectories
recursive: true

# Directory names to skip during traversal
skip_dirs:
  - ".git"
  - "__pycache__"
  - "_DELETE"

# Path to the SQLite database file (relative to project root or absolute)
database: "data/files.db"
```

## Example Workflow

### 1. Scan directories

```bash
just scan
```

```
Scanning: /Volumes/Photos
[1842 files found] Scanning ... 2024/vacation
  Inserted: 1842, Already in DB: 0

Scan complete.
  New files added: 1842
  Already in DB: 0
  Total files in database: 1842
```

### 2. Compute hashes

```bash
just hash
```

```
Total files in database: 1842
Already hashed: 0
Files to hash: 1842
Bytes to hash: 48 GB

[1/1842] [0/48 GB] [0.05%] Hashing ... 2024/vacation/IMG_001.CR3
[2/1842] [0/48 GB] [0.11%] [ETA 2h14m] Hashing ... 2024/vacation/IMG_002.CR3
...
```

Interrupt at any time. Next run picks up where you left off.

### 3. Find duplicates

```bash
just duplicates
```

```
Total hashed files analyzed: 1842
Duplicate files found: 430
Duplicate groups: 186

Distribution:
  172 groups with 2 copies each
  14 groups with 3 copies each

Reclaimable space: 12.50 GB
```

### 4. Clean up interactively

```bash
just cleanup
```

```
Analyzing duplicate files by folder...
Found 186 duplicate groups across 12 folders.

Select folders to remove duplicates from (Space to toggle, Enter to confirm):
[ ] trip-backup/photos/     (247 duplicates, 12.50 GB)
[ ] old-drive/raw/          (183 duplicates, 8.30 GB)
[ ] copies/2024/            ( 42 duplicates, 1.70 GB)
```

Select folders with Space, press Enter, review the dry-run report:

```
Files to delete (1 folders selected):

  trip-backup/photos/IMG_001.CR3  (25.50 MB)  -- kept in: raw/2024/IMG_001.CR3
  trip-backup/photos/IMG_002.CR3  (25.10 MB)  -- kept in: raw/2024/IMG_002.CR3
  ...

  Total: 247 files, 12.50 GB

Proceed with deletion? [y/N]
```

Type `y` to confirm. Files are deleted from disk and removed from the database.

## Contributing

### Development Setup

```bash
just init          # Install all dependencies including dev tools
just test          # Run the test suite
just ci-quiet      # Run all 11 validation checks
```

### Running Checks

| Command | What it does |
|---------|-------------|
| `just test` | Run all tests (pytest) |
| `just test-coverage` | Run tests with coverage report |
| `just code-format` | Auto-fix formatting (ruff) |
| `just code-style` | Check formatting without modifying (ruff) |
| `just code-typecheck` | Type checking (mypy) |
| `just code-lspchecks` | Strict type checking (pyright) |
| `just code-security` | Security scan (bandit) |
| `just code-semgrep` | Custom static analysis rules |
| `just code-deptry` | Dependency hygiene |
| `just code-spell` | Spell checking |
| `just code-audit` | Dependency vulnerability scan |
| `just ci` | Run all of the above (verbose) |
| `just ci-quiet` | Run all of the above (silent, fail-fast) |

### Database Schema

The tool uses a single SQLite database with WAL journal mode. One table, three indexes:

```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,           -- base filename (e.g., "IMG_001.CR3")
    rel_path TEXT NOT NULL UNIQUE,    -- path relative to scan root
    extension TEXT NOT NULL,          -- file extension including dot
    md5_hash TEXT,                    -- NULL until hashed
    sha256_hash TEXT,                 -- NULL until hashed
    file_size INTEGER NOT NULL,       -- size in bytes
    hashed_at TEXT                    -- ISO-8601 timestamp, NULL until hashed
);

CREATE INDEX idx_files_md5_hash ON files (md5_hash);
CREATE INDEX idx_files_sha256_hash ON files (sha256_hash);
CREATE INDEX idx_files_file_size ON files (file_size);
```

Duplicates are identified by grouping on `(file_size, md5_hash, sha256_hash)`. The `rel_path` UNIQUE constraint prevents the same file from being inserted twice.

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
  test_cleanup.py       # Cleanup unit tests (21 tests)
  test_cleanup_e2e.py   # End-to-end tests with real files on disk (5 tests)
  test_config.py        # Config loading and validation tests
  test_database.py      # Database operation tests
  test_hasher.py        # Hasher tests
  test_scanner.py       # Scanner tests
```

### Dev Notes

- All Python execution uses `uv run`, never `python` directly
- All tasks use `just <target>`, never running scripts directly
- The test suite includes end-to-end tests that create real files on disk, run the full scan/hash/cleanup pipeline, and verify both disk and database state after deletion
- `simple-term-menu` is used for the interactive TUI (lazy-imported only when a terminal is available)
- The cleanup module exposes analysis and deletion functions separately from the TUI, so tests can exercise the full pipeline without needing terminal interaction

## License

This project is licensed under the [MIT License](LICENSE).
