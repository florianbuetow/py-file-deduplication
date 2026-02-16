# Interactive Duplicate Folder Cleanup

## Problem

After scanning and hashing files, the user needs a way to selectively remove duplicate files. Duplicates often cluster by folder (e.g., backup copies of entire directories), so the natural unit of selection is the folder, not individual files.

## Solution

A text-based interactive menu that ranks folders by duplicate count, lets the user select which folders' duplicates to remove, shows a dry-run report, and executes deletion with last-copy protection.

## Data Model & Analysis

The analysis pipeline:

1. **Build duplicate groups** from the database, reusing the existing grouping logic (key = `file_size + md5 + sha256`). Only groups with 2+ files qualify.
2. **Compute per-folder stats** for each folder containing at least one duplicate:
   - `duplicate_count`: number of files in this folder that have copies elsewhere
   - `reclaimable_bytes`: total size of those duplicate files
   - `duplicate_files`: list of `(rel_path, file_size, group_key)` tuples
3. **Rank folders** by `duplicate_count` descending, secondary sort by `reclaimable_bytes` descending.
4. **Folder** = the directory part of `rel_path` (e.g., `trip1/photos/` from `trip1/photos/IMG_001.CR3`).

## Interactive TUI

Uses `simple-term-menu` with `multi_select=True`.

Menu display:
```
[ ] trip-backup/photos/     (247 duplicates, 12.50 GB reclaimable)
[ ] old-drive/raw/          (183 duplicates, 8.30 GB reclaimable)
[ ] copies/2024/            ( 42 duplicates, 1.70 GB reclaimable)
```

Interaction:
- Arrow keys or j/k to navigate
- Space/Tab to toggle checkboxes
- Built-in search to filter folders by typing
- Enter to confirm, Escape/q to cancel

## Dry-Run Report

After selection, before any deletion:
```
Files to delete (3 folders selected):

  trip-backup/photos/IMG_001.CR3  (25.5 MB)  -- kept in: raw/2024/IMG_001.CR3
  trip-backup/photos/IMG_002.CR3  (25.1 MB)  -- kept in: raw/2024/IMG_002.CR3
  ...

  Total: 247 files, 12.50 GB

  Warning: 3 files skipped (last copy protection)

Proceed with deletion? [y/N]
```

Each file shows where a surviving copy lives. Files protected by last-copy rules are listed separately.

## Safety: Last-Copy Protection

For each duplicate group, if ALL folders containing copies are selected for removal, keep the first copy by alphabetical path and only delete the rest.

Examples:
- File in folders A, B, C; select all three: A survives (alphabetically first), B and C deleted.
- File in folders A, B, C; select B and C: both deleted, A already safe.

## Deletion Execution

1. Delete file from disk (`os.remove`)
2. Remove entry from database
3. Track successes and failures separately
4. If file already gone from disk, skip gracefully and clean up DB entry
5. Commit database changes in batches (every 100 deletions)

Final summary:
```
Deleted: 244 files (12.48 GB)
Failed:    3 files (see warnings above)
Skipped:   3 files (last copy protection)
```

## Module Structure

New files:
- `src/app/cleanup.py` -- folder analysis, dry-run report, deletion logic, TUI menu
- `src/cleanup.py` -- entry point script
- `tests/test_cleanup.py` -- unit tests for analysis and safety logic
- `tests/test_cleanup_e2e.py` -- end-to-end test with real files on disk

Changes to existing files:
- `src/app/__init__.py` -- export `run_cleanup`
- `src/app/cli.py` -- add `run_cleanup()` handler
- `src/app/database.py` -- add single-row deletion if needed
- `justfile` -- add `cleanup` recipe
- `pyproject.toml` -- add `simple-term-menu` as runtime dependency

CLI invocation: `just cleanup`

## End-to-End Testing

Test creates an isolated directory structure with known duplicates:

```
tmp_test_dir/
  config.yaml          -- points only at test folders
  test.db              -- isolated database
  originals/
    photo1.raw         -- unique content "AAAA..."
    photo2.raw         -- unique content "BBBB..."
    photo3.raw         -- unique content "CCCC..."
  backup1/
    photo1.raw         -- duplicate of originals/photo1.raw
    photo2.raw         -- duplicate of originals/photo2.raw
  backup2/
    photo1.raw         -- duplicate of originals/photo1.raw
    photo2.raw         -- duplicate of originals/photo2.raw
    photo3.raw         -- duplicate of originals/photo3.raw
  unique_folder/
    solo.raw           -- no duplicates
```

Test flow:
1. Run `uv run src/scan.py` with test config to populate database
2. Run `uv run src/hash.py` with test config to compute hashes
3. Verify folder analysis produces correct rankings
4. Simulate selecting `backup1` for removal, confirm deletion
5. Assert deleted files are gone from disk and database
6. Assert all other files still exist
7. Test last-copy protection by selecting all remaining folders for a file

The TUI menu is bypassed in tests -- the cleanup module exposes analysis and deletion functions separately, so e2e tests exercise real files, real scan/hash CLI, and real deletion without needing terminal interaction.

## Dependencies

- `simple-term-menu` (runtime) -- lightweight, zero-dependency terminal menu library

## Non-Interactive Detection

If stdout is not a terminal (piped output), the command exits with a clear error message since the TUI requires an interactive terminal.
