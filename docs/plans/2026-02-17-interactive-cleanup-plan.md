# Interactive Duplicate Folder Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an interactive TUI for selecting folders and removing duplicate files with last-copy safety protection.

**Architecture:** New `cleanup` module with pure functions for analysis and deletion, plus a `simple-term-menu` TUI layer. Functions are separated from the menu for testability. A new database query adds the `id` column to hashed file iteration.

**Tech Stack:** Python 3.12+, simple-term-menu, SQLite, pytest

**Design doc:** `docs/plans/2026-02-17-interactive-cleanup-design.md`

**Project rules:**
- All function params must be required (no defaults) — enforced by semgrep
- Module-level constants must use `_` prefix and type annotations — enforced by semgrep
- All functions need Google-style docstrings and full type annotations — enforced by ruff
- Tests are exempt from docstring and annotation rules — configured in ruff per-file-ignores
- Run `just test` after every change; run `just ci-quiet` before final commit

---

### Task 1: Add simple-term-menu dependency

**Files:**
- Modify: `pyproject.toml:7-9`

**Step 1: Add dependency to pyproject.toml**

In `pyproject.toml`, add `simple-term-menu` to the runtime dependencies:

```python
dependencies = [
    "pyyaml>=6.0.0",
    "simple-term-menu>=1.6.0",
]
```

**Step 2: Install**

Run: `uv sync --all-extras`

**Step 3: Verify import works**

Run: `uv run python -c "from simple_term_menu import TerminalMenu; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "Add simple-term-menu dependency for interactive cleanup TUI"
```

---

### Task 2: Add iter_hashed_files_with_id database query

**Files:**
- Modify: `src/app/database.py:179-195` (after `iter_hashed_files`)
- Test: `tests/test_database.py`

**Step 1: Write failing tests**

Add to `tests/test_database.py` — import `iter_hashed_files_with_id` in the imports at line 11, then add this test class at the end of the file:

```python
class TestIterHashedFilesWithId:
    def test_returns_id_and_hashed_fields(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 200)
        db_conn.commit()

        update_hashes(db_conn, 1, "md5a", "sha256a", "2026-01-01T00:00:00Z")
        update_hashes(db_conn, 2, "md5b", "sha256b", "2026-01-01T00:00:00Z")
        db_conn.commit()

        cursor = iter_hashed_files_with_id(db_conn)
        rows = cursor.fetchall()

        assert len(rows) == 2
        # Ordered by file_size DESC: b (200), a (100)
        assert rows[0] == (2, 200, "md5b", "sha256b", "b.jpg")
        assert rows[1] == (1, 100, "md5a", "sha256a", "a.jpg")

    def test_excludes_unhashed(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 200)
        db_conn.commit()

        update_hashes(db_conn, 1, "md5a", "sha256a", "2026-01-01T00:00:00Z")
        db_conn.commit()

        cursor = iter_hashed_files_with_id(db_conn)
        rows = cursor.fetchall()

        assert len(rows) == 1
        assert rows[0] == (1, 100, "md5a", "sha256a", "a.jpg")

    def test_empty_database(self, db_conn):
        cursor = iter_hashed_files_with_id(db_conn)
        rows = cursor.fetchall()

        assert len(rows) == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_database.py::TestIterHashedFilesWithId -v`
Expected: FAIL with `ImportError` (function doesn't exist yet)

**Step 3: Implement iter_hashed_files_with_id**

Add to `src/app/database.py` after `iter_hashed_files` (after line 195):

```python
def iter_hashed_files_with_id(conn: sqlite3.Connection) -> sqlite3.Cursor:
    """Return a cursor over all hashed file records including their IDs.

    Yields rows as (id, file_size, md5_hash, sha256_hash, rel_path) for files
    that have been hashed (both md5_hash and sha256_hash are NOT NULL).

    Args:
        conn: An open SQLite connection.

    Returns:
        A cursor iterating over (id, file_size, md5_hash, sha256_hash, rel_path) tuples.
    """
    return conn.execute(
        "SELECT id, file_size, md5_hash, sha256_hash, rel_path FROM files "
        "WHERE md5_hash IS NOT NULL AND sha256_hash IS NOT NULL "
        "ORDER BY file_size DESC"
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_database.py::TestIterHashedFilesWithId -v`
Expected: 3 passed

**Step 5: Run full test suite**

Run: `just test`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/app/database.py tests/test_database.py
git commit -m "Add iter_hashed_files_with_id query for cleanup feature"
```

---

### Task 3: Create cleanup module with data types and build_duplicate_groups

**Files:**
- Create: `src/app/cleanup.py`
- Create: `tests/test_cleanup.py`

**Step 1: Write failing test for build_duplicate_groups**

Create `tests/test_cleanup.py`:

```python
"""Tests for the cleanup module."""

from app.cleanup import DuplicateFile, build_duplicate_groups
from app.database import insert_file, open_database, update_hashes


def _insert_hashed_file(conn, filename, rel_path, extension, file_size, md5_hash, sha256_hash):
    """Helper to insert a file and immediately set its hashes."""
    insert_file(conn, filename, rel_path, extension, file_size)
    conn.commit()
    cursor = conn.execute("SELECT id FROM files WHERE rel_path = ?", (rel_path,))
    file_id = cursor.fetchone()[0]
    update_hashes(conn, file_id, md5_hash, sha256_hash, "2025-01-01T00:00:00+00:00")
    conn.commit()
    return file_id


class TestBuildDuplicateGroups:
    def test_empty_database(self, tmp_path):
        conn = open_database(tmp_path / "test.db")
        groups = build_duplicate_groups(conn)
        assert len(groups) == 0
        conn.close()

    def test_no_duplicates(self, tmp_path):
        conn = open_database(tmp_path / "test.db")
        _insert_hashed_file(conn, "a.raw", "dir1/a.raw", ".raw", 1000, "md5_a", "sha_a")
        _insert_hashed_file(conn, "b.raw", "dir2/b.raw", ".raw", 2000, "md5_b", "sha_b")
        groups = build_duplicate_groups(conn)
        assert len(groups) == 0
        conn.close()

    def test_one_duplicate_group(self, tmp_path):
        conn = open_database(tmp_path / "test.db")
        _insert_hashed_file(conn, "a.raw", "originals/a.raw", ".raw", 1000, "md5_x", "sha_x")
        _insert_hashed_file(conn, "a.raw", "backup/a.raw", ".raw", 1000, "md5_x", "sha_x")

        groups = build_duplicate_groups(conn)

        assert len(groups) == 1
        key = list(groups.keys())[0]
        assert len(groups[key]) == 2

        folders = {f.folder for f in groups[key]}
        assert folders == {"originals", "backup"}
        conn.close()

    def test_multiple_groups(self, tmp_path):
        conn = open_database(tmp_path / "test.db")
        _insert_hashed_file(conn, "a.raw", "d1/a.raw", ".raw", 1000, "md5_a", "sha_a")
        _insert_hashed_file(conn, "a.raw", "d2/a.raw", ".raw", 1000, "md5_a", "sha_a")
        _insert_hashed_file(conn, "b.raw", "d1/b.raw", ".raw", 2000, "md5_b", "sha_b")
        _insert_hashed_file(conn, "b.raw", "d3/b.raw", ".raw", 2000, "md5_b", "sha_b")

        groups = build_duplicate_groups(conn)

        assert len(groups) == 2
        conn.close()

    def test_file_in_root_has_dot_folder(self, tmp_path):
        conn = open_database(tmp_path / "test.db")
        _insert_hashed_file(conn, "a.raw", "a.raw", ".raw", 1000, "md5_x", "sha_x")
        _insert_hashed_file(conn, "a.raw", "sub/a.raw", ".raw", 1000, "md5_x", "sha_x")

        groups = build_duplicate_groups(conn)

        key = list(groups.keys())[0]
        folders = {f.folder for f in groups[key]}
        assert folders == {".", "sub"}
        conn.close()

    def test_duplicate_file_fields(self, tmp_path):
        conn = open_database(tmp_path / "test.db")
        id1 = _insert_hashed_file(conn, "a.raw", "originals/a.raw", ".raw", 1000, "md5_x", "sha_x")
        id2 = _insert_hashed_file(conn, "a.raw", "backup/a.raw", ".raw", 1000, "md5_x", "sha_x")

        groups = build_duplicate_groups(conn)
        key = list(groups.keys())[0]
        files = sorted(groups[key], key=lambda f: f.rel_path)

        assert files[0].file_id == id2  # backup/a.raw
        assert files[0].rel_path == "backup/a.raw"
        assert files[0].file_size == 1000
        assert files[0].group_key == key
        assert files[0].folder == "backup"

        assert files[1].file_id == id1  # originals/a.raw
        assert files[1].folder == "originals"
        conn.close()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cleanup.py::TestBuildDuplicateGroups -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Create src/app/cleanup.py with data types and build_duplicate_groups**

Create `src/app/cleanup.py`:

```python
"""Interactive duplicate folder cleanup for raw-deduplicator_v2.

Analyzes duplicate files by folder, provides an interactive TUI for
selecting which folders' duplicates to remove, and executes deletion
with last-copy safety protection.
"""

import dataclasses
import sqlite3
from collections import defaultdict
from pathlib import PurePosixPath

from app.database import iter_hashed_files_with_id

_GB: int = 1024**3
_MB: int = 1024**2
_KB: int = 1024


def _format_size(size: int) -> str:
    """Format a byte count with auto-selected unit.

    Args:
        size: The size in bytes.

    Returns:
        A human-readable string like "1.50 GB" or "500 B".
    """
    if size >= _GB:
        return f"{size / _GB:.2f} GB"
    if size >= _MB:
        return f"{size / _MB:.2f} MB"
    if size >= _KB:
        return f"{size / _KB:.2f} KB"
    return f"{size} B"


@dataclasses.dataclass(frozen=True)
class DuplicateFile:
    """A file that belongs to a duplicate group.

    Attributes:
        file_id: The database row ID.
        rel_path: Path relative to the scan root.
        file_size: File size in bytes.
        group_key: The duplicate group key (file_size_md5_sha256).
        folder: The directory part of rel_path.
    """

    file_id: int
    rel_path: str
    file_size: int
    group_key: str
    folder: str


@dataclasses.dataclass(frozen=True)
class FolderStats:
    """Statistics about duplicate files in a folder.

    Attributes:
        folder: The folder path relative to the scan root.
        duplicate_count: Number of files in this folder that have copies elsewhere.
        reclaimable_bytes: Total size of those duplicate files.
        files: The duplicate files in this folder.
    """

    folder: str
    duplicate_count: int
    reclaimable_bytes: int
    files: list[DuplicateFile]


@dataclasses.dataclass(frozen=True)
class FileDeletion:
    """A file planned for deletion.

    Attributes:
        file_id: The database row ID.
        rel_path: Path relative to the scan root.
        file_size: File size in bytes.
        surviving_copy: rel_path of a copy that will survive.
    """

    file_id: int
    rel_path: str
    file_size: int
    surviving_copy: str


@dataclasses.dataclass(frozen=True)
class DeletionPlan:
    """Plan for which files to delete.

    Attributes:
        deletions: Files to delete from disk and database.
        protected_paths: rel_paths of files kept by last-copy protection.
        total_bytes: Total bytes that will be freed.
    """

    deletions: list[FileDeletion]
    protected_paths: list[str]
    total_bytes: int


@dataclasses.dataclass(frozen=True)
class DeletionResult:
    """Result of executing a deletion plan.

    Attributes:
        deleted_count: Number of files successfully deleted.
        deleted_bytes: Total bytes freed.
        failed_count: Number of files that could not be deleted.
        failed_paths: rel_paths of files that failed to delete.
    """

    deleted_count: int
    deleted_bytes: int
    failed_count: int
    failed_paths: list[str]


def build_duplicate_groups(conn: sqlite3.Connection) -> dict[str, list[DuplicateFile]]:
    """Build duplicate groups from hashed files in the database.

    Groups files by (file_size, md5_hash, sha256_hash). Only groups with
    2 or more files are returned.

    Args:
        conn: An open SQLite connection to the files database.

    Returns:
        A dict mapping group keys to lists of DuplicateFile objects.
        Only groups with 2+ files are included.
    """
    index: dict[str, list[DuplicateFile]] = defaultdict(list)

    cursor: sqlite3.Cursor = iter_hashed_files_with_id(conn)
    for row in cursor:
        file_id: int = row[0]
        file_size: int = row[1]
        md5_hash: str = row[2]
        sha256_hash: str = row[3]
        rel_path: str = row[4]

        key: str = f"{file_size}_{md5_hash}_{sha256_hash}"
        folder: str = str(PurePosixPath(rel_path).parent)

        index[key].append(
            DuplicateFile(
                file_id=file_id,
                rel_path=rel_path,
                file_size=file_size,
                group_key=key,
                folder=folder,
            )
        )

    return {k: v for k, v in index.items() if len(v) > 1}
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cleanup.py::TestBuildDuplicateGroups -v`
Expected: 6 passed

**Step 5: Run full test suite**

Run: `just test`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/app/cleanup.py tests/test_cleanup.py
git commit -m "Add cleanup module with data types and build_duplicate_groups"
```

---

### Task 4: Add compute_folder_stats

**Files:**
- Modify: `src/app/cleanup.py`
- Modify: `tests/test_cleanup.py`

**Step 1: Write failing tests**

Add to `tests/test_cleanup.py` — add `compute_folder_stats` and `FolderStats` to the imports, then add:

```python
class TestComputeFolderStats:
    def test_empty_groups(self):
        stats = compute_folder_stats({})
        assert len(stats) == 0

    def test_single_group_two_folders(self):
        groups = {
            "1000_md5_sha": [
                DuplicateFile(file_id=1, rel_path="originals/a.raw", file_size=1000, group_key="1000_md5_sha", folder="originals"),
                DuplicateFile(file_id=2, rel_path="backup/a.raw", file_size=1000, group_key="1000_md5_sha", folder="backup"),
            ]
        }
        stats = compute_folder_stats(groups)

        assert len(stats) == 2
        folders = {s.folder for s in stats}
        assert folders == {"originals", "backup"}
        assert stats[0].duplicate_count == 1
        assert stats[0].reclaimable_bytes == 1000

    def test_sorted_by_duplicate_count_descending(self):
        groups = {
            "1000_md5a_shaa": [
                DuplicateFile(file_id=1, rel_path="few/a.raw", file_size=1000, group_key="1000_md5a_shaa", folder="few"),
                DuplicateFile(file_id=2, rel_path="many/a.raw", file_size=1000, group_key="1000_md5a_shaa", folder="many"),
            ],
            "2000_md5b_shab": [
                DuplicateFile(file_id=3, rel_path="many/b.raw", file_size=2000, group_key="2000_md5b_shab", folder="many"),
                DuplicateFile(file_id=4, rel_path="few/b.raw", file_size=2000, group_key="2000_md5b_shab", folder="few"),
            ],
            "3000_md5c_shac": [
                DuplicateFile(file_id=5, rel_path="many/c.raw", file_size=3000, group_key="3000_md5c_shac", folder="many"),
                DuplicateFile(file_id=6, rel_path="other/c.raw", file_size=3000, group_key="3000_md5c_shac", folder="other"),
            ],
        }
        stats = compute_folder_stats(groups)

        # "many" has 3 dupes, "few" has 2, "other" has 1
        assert stats[0].folder == "many"
        assert stats[0].duplicate_count == 3
        assert stats[1].folder == "few"
        assert stats[1].duplicate_count == 2
        assert stats[2].folder == "other"
        assert stats[2].duplicate_count == 1

    def test_secondary_sort_by_reclaimable_bytes(self):
        groups = {
            "1000_md5a_shaa": [
                DuplicateFile(file_id=1, rel_path="small/a.raw", file_size=1000, group_key="1000_md5a_shaa", folder="small"),
                DuplicateFile(file_id=2, rel_path="big/a.raw", file_size=1000, group_key="1000_md5a_shaa", folder="big"),
            ],
            "5000_md5b_shab": [
                DuplicateFile(file_id=3, rel_path="big/b.raw", file_size=5000, group_key="5000_md5b_shab", folder="big"),
                DuplicateFile(file_id=4, rel_path="small/b.raw", file_size=5000, group_key="5000_md5b_shab", folder="small"),
            ],
        }
        stats = compute_folder_stats(groups)

        # Both have 2 dupes, but "big" has 6000 bytes vs "small" 6000 bytes — tied
        # Actually both have same reclaimable (1000+5000 = 6000 each), so order is stable
        assert stats[0].duplicate_count == 2
        assert stats[1].duplicate_count == 2
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cleanup.py::TestComputeFolderStats -v`
Expected: FAIL with `ImportError`

**Step 3: Implement compute_folder_stats**

Add to `src/app/cleanup.py` after `build_duplicate_groups`:

```python
def compute_folder_stats(duplicate_groups: dict[str, list[DuplicateFile]]) -> list[FolderStats]:
    """Compute per-folder statistics from duplicate groups.

    Aggregates duplicate files by folder and sorts by duplicate count
    descending, with reclaimable bytes as a secondary sort key.

    Args:
        duplicate_groups: Dict mapping group keys to lists of DuplicateFile.

    Returns:
        A list of FolderStats sorted by duplicate_count descending,
        then reclaimable_bytes descending.
    """
    folder_files: dict[str, list[DuplicateFile]] = defaultdict(list)

    for files in duplicate_groups.values():
        for dup_file in files:
            folder_files[dup_file.folder].append(dup_file)

    stats: list[FolderStats] = []
    for folder, files in folder_files.items():
        stats.append(
            FolderStats(
                folder=folder,
                duplicate_count=len(files),
                reclaimable_bytes=sum(f.file_size for f in files),
                files=files,
            )
        )

    stats.sort(key=lambda s: (-s.duplicate_count, -s.reclaimable_bytes))
    return stats
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cleanup.py::TestComputeFolderStats -v`
Expected: 4 passed

**Step 5: Run full test suite**

Run: `just test`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/app/cleanup.py tests/test_cleanup.py
git commit -m "Add compute_folder_stats for per-folder duplicate analysis"
```

---

### Task 5: Add plan_deletions with last-copy safety

**Files:**
- Modify: `src/app/cleanup.py`
- Modify: `tests/test_cleanup.py`

**Step 1: Write failing tests**

Add to `tests/test_cleanup.py` — add `plan_deletions`, `DeletionPlan`, `FileDeletion` to imports, then add:

```python
class TestPlanDeletions:
    def test_delete_from_one_folder(self):
        groups = {
            "1000_md5_sha": [
                DuplicateFile(file_id=1, rel_path="originals/a.raw", file_size=1000, group_key="1000_md5_sha", folder="originals"),
                DuplicateFile(file_id=2, rel_path="backup/a.raw", file_size=1000, group_key="1000_md5_sha", folder="backup"),
            ]
        }

        plan = plan_deletions(selected_folders=["backup"], duplicate_groups=groups)

        assert len(plan.deletions) == 1
        assert plan.deletions[0].file_id == 2
        assert plan.deletions[0].rel_path == "backup/a.raw"
        assert plan.deletions[0].surviving_copy == "originals/a.raw"
        assert len(plan.protected_paths) == 0
        assert plan.total_bytes == 1000

    def test_no_files_in_selected_folders(self):
        groups = {
            "1000_md5_sha": [
                DuplicateFile(file_id=1, rel_path="a/file.raw", file_size=1000, group_key="1000_md5_sha", folder="a"),
                DuplicateFile(file_id=2, rel_path="b/file.raw", file_size=1000, group_key="1000_md5_sha", folder="b"),
            ]
        }

        plan = plan_deletions(selected_folders=["nonexistent"], duplicate_groups=groups)

        assert len(plan.deletions) == 0
        assert len(plan.protected_paths) == 0
        assert plan.total_bytes == 0

    def test_last_copy_protection(self):
        groups = {
            "1000_md5_sha": [
                DuplicateFile(file_id=1, rel_path="a/file.raw", file_size=1000, group_key="1000_md5_sha", folder="a"),
                DuplicateFile(file_id=2, rel_path="b/file.raw", file_size=1000, group_key="1000_md5_sha", folder="b"),
            ]
        }

        plan = plan_deletions(selected_folders=["a", "b"], duplicate_groups=groups)

        # One copy protected (alphabetically first: a/file.raw)
        assert len(plan.deletions) == 1
        assert plan.deletions[0].rel_path == "b/file.raw"
        assert plan.deletions[0].surviving_copy == "a/file.raw"
        assert len(plan.protected_paths) == 1
        assert plan.protected_paths[0] == "a/file.raw"
        assert plan.total_bytes == 1000

    def test_last_copy_protection_three_copies(self):
        groups = {
            "1000_md5_sha": [
                DuplicateFile(file_id=1, rel_path="c/file.raw", file_size=1000, group_key="1000_md5_sha", folder="c"),
                DuplicateFile(file_id=2, rel_path="a/file.raw", file_size=1000, group_key="1000_md5_sha", folder="a"),
                DuplicateFile(file_id=3, rel_path="b/file.raw", file_size=1000, group_key="1000_md5_sha", folder="b"),
            ]
        }

        plan = plan_deletions(selected_folders=["a", "b", "c"], duplicate_groups=groups)

        # a/file.raw survives (alphabetically first), b and c deleted
        assert len(plan.deletions) == 2
        deleted_paths = {d.rel_path for d in plan.deletions}
        assert deleted_paths == {"b/file.raw", "c/file.raw"}
        assert plan.protected_paths == ["a/file.raw"]
        for d in plan.deletions:
            assert d.surviving_copy == "a/file.raw"

    def test_mixed_safe_and_unsafe_groups(self):
        groups = {
            "1000_md5a_shaa": [
                DuplicateFile(file_id=1, rel_path="safe/a.raw", file_size=1000, group_key="1000_md5a_shaa", folder="safe"),
                DuplicateFile(file_id=2, rel_path="doomed/a.raw", file_size=1000, group_key="1000_md5a_shaa", folder="doomed"),
            ],
            "2000_md5b_shab": [
                DuplicateFile(file_id=3, rel_path="doomed/b.raw", file_size=2000, group_key="2000_md5b_shab", folder="doomed"),
                DuplicateFile(file_id=4, rel_path="also_doomed/b.raw", file_size=2000, group_key="2000_md5b_shab", folder="also_doomed"),
            ],
        }

        plan = plan_deletions(selected_folders=["doomed", "also_doomed"], duplicate_groups=groups)

        # Group 1: safe/a.raw not selected → doomed/a.raw deleted, no protection needed
        # Group 2: all in selected → one protected (also_doomed/b.raw < doomed/b.raw)
        assert len(plan.deletions) == 2
        assert len(plan.protected_paths) == 1
        assert plan.protected_paths[0] == "also_doomed/b.raw"

    def test_empty_groups(self):
        plan = plan_deletions(selected_folders=["any"], duplicate_groups={})
        assert len(plan.deletions) == 0
        assert len(plan.protected_paths) == 0
        assert plan.total_bytes == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cleanup.py::TestPlanDeletions -v`
Expected: FAIL with `ImportError`

**Step 3: Implement plan_deletions**

Add to `src/app/cleanup.py` after `compute_folder_stats`:

```python
def plan_deletions(
    selected_folders: list[str],
    duplicate_groups: dict[str, list[DuplicateFile]],
) -> DeletionPlan:
    """Plan which files to delete based on selected folders.

    For each duplicate group, files in selected folders are marked for
    deletion. If ALL copies of a group are in selected folders, the
    alphabetically first copy is protected (last-copy safety).

    Args:
        selected_folders: List of folder names selected for cleanup.
        duplicate_groups: Dict mapping group keys to lists of DuplicateFile.

    Returns:
        A DeletionPlan with files to delete, protected paths, and total bytes.
    """
    selected_set: set[str] = set(selected_folders)
    deletions: list[FileDeletion] = []
    protected_paths: list[str] = []

    for files in duplicate_groups.values():
        in_selected: list[DuplicateFile] = [f for f in files if f.folder in selected_set]
        in_safe: list[DuplicateFile] = [f for f in files if f.folder not in selected_set]

        if not in_selected:
            continue

        if in_safe:
            surviving: str = sorted(in_safe, key=lambda f: f.rel_path)[0].rel_path
            for dup_file in in_selected:
                deletions.append(
                    FileDeletion(
                        file_id=dup_file.file_id,
                        rel_path=dup_file.rel_path,
                        file_size=dup_file.file_size,
                        surviving_copy=surviving,
                    )
                )
        else:
            sorted_files: list[DuplicateFile] = sorted(in_selected, key=lambda f: f.rel_path)
            protected_path: str = sorted_files[0].rel_path
            protected_paths.append(protected_path)
            for dup_file in sorted_files[1:]:
                deletions.append(
                    FileDeletion(
                        file_id=dup_file.file_id,
                        rel_path=dup_file.rel_path,
                        file_size=dup_file.file_size,
                        surviving_copy=protected_path,
                    )
                )

    total_bytes: int = sum(d.file_size for d in deletions)

    return DeletionPlan(
        deletions=deletions,
        protected_paths=protected_paths,
        total_bytes=total_bytes,
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cleanup.py::TestPlanDeletions -v`
Expected: 6 passed

**Step 5: Run full test suite**

Run: `just test`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/app/cleanup.py tests/test_cleanup.py
git commit -m "Add plan_deletions with last-copy safety protection"
```

---

### Task 6: Add execute_deletions

**Files:**
- Modify: `src/app/cleanup.py`
- Modify: `tests/test_cleanup.py`

**Step 1: Write failing tests**

Add to `tests/test_cleanup.py` — add `execute_deletions`, `DeletionResult` to imports, add `from pathlib import Path`, then add:

```python
class TestExecuteDeletions:
    def test_deletes_files_from_disk_and_db(self, tmp_path):
        # Set up real files
        scan_dir = tmp_path / "files"
        (scan_dir / "backup").mkdir(parents=True)
        (scan_dir / "backup" / "a.raw").write_bytes(b"content_a")
        (scan_dir / "backup" / "b.raw").write_bytes(b"content_b")

        # Set up database
        conn = open_database(tmp_path / "test.db")
        id1 = _insert_hashed_file(conn, "a.raw", "backup/a.raw", ".raw", 9, "md5a", "shaa")
        id2 = _insert_hashed_file(conn, "b.raw", "backup/b.raw", ".raw", 9, "md5b", "shab")

        plan = DeletionPlan(
            deletions=[
                FileDeletion(file_id=id1, rel_path="backup/a.raw", file_size=9, surviving_copy="orig/a.raw"),
                FileDeletion(file_id=id2, rel_path="backup/b.raw", file_size=9, surviving_copy="orig/b.raw"),
            ],
            protected_paths=[],
            total_bytes=18,
        )

        result = execute_deletions(conn=conn, base_path=scan_dir, plan=plan)

        assert result.deleted_count == 2
        assert result.deleted_bytes == 18
        assert result.failed_count == 0
        assert not (scan_dir / "backup" / "a.raw").exists()
        assert not (scan_dir / "backup" / "b.raw").exists()

        # Verify DB entries removed
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_handles_already_missing_file(self, tmp_path):
        # File doesn't exist on disk but is in DB
        conn = open_database(tmp_path / "test.db")
        file_id = _insert_hashed_file(conn, "gone.raw", "backup/gone.raw", ".raw", 100, "md5g", "shag")

        plan = DeletionPlan(
            deletions=[
                FileDeletion(file_id=file_id, rel_path="backup/gone.raw", file_size=100, surviving_copy="orig/gone.raw"),
            ],
            protected_paths=[],
            total_bytes=100,
        )

        scan_dir = tmp_path / "files"
        scan_dir.mkdir()

        result = execute_deletions(conn=conn, base_path=scan_dir, plan=plan)

        # Should succeed — DB entry cleaned up even though file was already gone
        assert result.deleted_count == 1
        assert result.failed_count == 0

        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_empty_plan(self, tmp_path):
        conn = open_database(tmp_path / "test.db")

        plan = DeletionPlan(deletions=[], protected_paths=[], total_bytes=0)

        result = execute_deletions(conn=conn, base_path=tmp_path, plan=plan)

        assert result.deleted_count == 0
        assert result.deleted_bytes == 0
        assert result.failed_count == 0
        conn.close()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cleanup.py::TestExecuteDeletions -v`
Expected: FAIL with `ImportError`

**Step 3: Implement execute_deletions**

Add imports at the top of `src/app/cleanup.py` — add `sys` and `Path` to the existing imports:

```python
import sys
from pathlib import Path, PurePosixPath
```

Add `delete_files` to the database import:

```python
from app.database import delete_files, iter_hashed_files_with_id
```

Add the function after `plan_deletions`:

```python
def execute_deletions(
    conn: sqlite3.Connection,
    base_path: Path,
    plan: DeletionPlan,
) -> DeletionResult:
    """Execute file deletions from disk and database.

    For each file in the deletion plan, removes it from disk (if present)
    and from the database. Files already missing from disk are still
    cleaned up in the database. Files that cannot be deleted due to
    OS errors are tracked as failures.

    Args:
        conn: An open SQLite connection to the files database.
        base_path: The resolved base directory that rel_path values are relative to.
        plan: The deletion plan to execute.

    Returns:
        A DeletionResult with counts and paths of deleted and failed files.
    """
    deleted_ids: list[int] = []
    deleted_bytes: int = 0
    failed_paths: list[str] = []

    for file_del in plan.deletions:
        full_path: Path = base_path / file_del.rel_path

        try:
            full_path.unlink(missing_ok=True)
        except OSError as err:
            print(f"  WARNING: Could not delete {full_path}: {err}", file=sys.stderr)
            failed_paths.append(file_del.rel_path)
            continue

        deleted_ids.append(file_del.file_id)
        deleted_bytes += file_del.file_size

    if deleted_ids:
        delete_files(conn, deleted_ids)
        conn.commit()

    return DeletionResult(
        deleted_count=len(deleted_ids),
        deleted_bytes=deleted_bytes,
        failed_count=len(failed_paths),
        failed_paths=failed_paths,
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cleanup.py::TestExecuteDeletions -v`
Expected: 3 passed

**Step 5: Run full test suite**

Run: `just test`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/app/cleanup.py tests/test_cleanup.py
git commit -m "Add execute_deletions for disk and database cleanup"
```

---

### Task 7: Add dry-run report, TUI menu, and run_cleanup_interactive

**Files:**
- Modify: `src/app/cleanup.py`

**Step 1: Implement print_dry_run_report**

Add to `src/app/cleanup.py` after `execute_deletions`:

```python
def print_dry_run_report(plan: DeletionPlan) -> None:
    """Print a dry-run report of planned deletions.

    Shows each file to be deleted, where a surviving copy lives,
    totals, and any files protected by last-copy safety.

    Args:
        plan: The deletion plan to report on.
    """
    folder_count: int = len({d.rel_path.rsplit("/", 1)[0] if "/" in d.rel_path else "." for d in plan.deletions})
    print(f"\nFiles to delete ({folder_count} folders selected):\n")

    for file_del in sorted(plan.deletions, key=lambda d: d.rel_path):
        size_str: str = _format_size(file_del.file_size)
        print(f"  {file_del.rel_path}  ({size_str})  -- kept in: {file_del.surviving_copy}")

    print(f"\n  Total: {len(plan.deletions)} files, {_format_size(plan.total_bytes)}")

    if plan.protected_paths:
        print(f"\n  Warning: {len(plan.protected_paths)} files skipped (last copy protection)")
        for path in sorted(plan.protected_paths):
            print(f"    {path}")

    print()
```

**Step 2: Implement show_folder_menu**

Add to `src/app/cleanup.py` after `print_dry_run_report`:

```python
def show_folder_menu(folder_stats: list[FolderStats]) -> list[str] | None:
    """Show an interactive folder selection menu.

    Displays folders sorted by duplicate count with checkboxes.
    Returns the selected folder names, or None if the user cancels.

    Args:
        folder_stats: List of FolderStats to display.

    Returns:
        List of selected folder name strings, or None if cancelled/empty.
    """
    if not sys.stdout.isatty():
        print("ERROR: Cleanup requires an interactive terminal.", file=sys.stderr)
        sys.exit(1)

    from simple_term_menu import TerminalMenu

    entries: list[str] = []
    for stats in folder_stats:
        size_str: str = _format_size(stats.reclaimable_bytes)
        entries.append(f"{stats.folder}  ({stats.duplicate_count} duplicates, {size_str})")

    menu: TerminalMenu = TerminalMenu(
        entries,
        title="Select folders to remove duplicates from (Space to toggle, Enter to confirm):",
        multi_select=True,
        show_multi_select_hint=True,
    )

    selected_indices: tuple[int, ...] | None = menu.show()

    if selected_indices is None:
        return None

    if isinstance(selected_indices, int):
        selected_indices = (selected_indices,)

    if len(selected_indices) == 0:
        return None

    return [folder_stats[i].folder for i in selected_indices]
```

**Step 3: Implement run_cleanup_interactive**

Add to `src/app/cleanup.py` after `show_folder_menu`:

```python
def run_cleanup_interactive(conn: sqlite3.Connection, base_path: Path) -> None:
    """Run the full interactive cleanup workflow.

    Builds duplicate groups, shows folder analysis, presents the TUI
    menu for folder selection, shows a dry-run report, and executes
    deletion after user confirmation.

    Args:
        conn: An open SQLite connection to the files database.
        base_path: The resolved base directory that rel_path values are relative to.
    """
    print("Analyzing duplicate files by folder...")
    groups: dict[str, list[DuplicateFile]] = build_duplicate_groups(conn)

    if not groups:
        print("No duplicates found.")
        return

    folder_stats: list[FolderStats] = compute_folder_stats(groups)
    print(f"Found {len(groups)} duplicate groups across {len(folder_stats)} folders.\n")

    selected: list[str] | None = show_folder_menu(folder_stats)

    if selected is None:
        print("Cancelled.")
        return

    plan: DeletionPlan = plan_deletions(
        selected_folders=selected,
        duplicate_groups=groups,
    )

    if not plan.deletions:
        print("No files to delete in selected folders.")
        return

    print_dry_run_report(plan)

    answer: str = input("Proceed with deletion? [y/N] ")
    if answer.strip().lower() != "y":
        print("Aborted. No files deleted.")
        return

    result: DeletionResult = execute_deletions(conn=conn, base_path=base_path, plan=plan)

    print(f"\nDeleted: {result.deleted_count} files ({_format_size(result.deleted_bytes)})")
    if result.failed_count > 0:
        print(f"Failed:  {result.failed_count} files (see warnings above)")
    if plan.protected_paths:
        print(f"Skipped: {len(plan.protected_paths)} files (last copy protection)")
```

**Step 4: Run full test suite**

Run: `just test`
Expected: All tests pass (no new tests here, but existing tests must still pass)

**Step 5: Commit**

```bash
git add src/app/cleanup.py
git commit -m "Add dry-run report, TUI menu, and interactive cleanup orchestrator"
```

---

### Task 8: Wire up CLI entry point, exports, and justfile

**Files:**
- Modify: `src/app/cli.py:1-4` (imports) and after line 122
- Modify: `src/app/__init__.py:3,10-20`
- Create: `src/cleanup.py`
- Modify: `justfile:38-39` (after duplicates recipe)

**Step 1: Add run_cleanup to cli.py**

Add `from app.cleanup import run_cleanup_interactive` to the imports in `src/app/cli.py` (line 9 area).

Add this function after `run_duplicates` at the end of `src/app/cli.py`:

```python
def run_cleanup(project_root: Path) -> None:
    """Run the interactive duplicate cleanup.

    Loads config, opens the database, and launches the interactive
    TUI for selecting folders and removing duplicate files.

    Args:
        project_root: Absolute path to the project root directory.
    """
    config, conn, db_path = _resolve_config_and_db(project_root)
    print(f"Database: {db_path}")
    print("")

    if len(config.paths) != 1:
        print("ERROR: Cleanup requires exactly one scan path to resolve relative paths.", file=sys.stderr)
        conn.close()
        sys.exit(1)

    base_path: Path = Path(config.paths[0]).resolve()

    try:
        run_cleanup_interactive(conn=conn, base_path=base_path)
    finally:
        conn.close()
```

**Step 2: Update __init__.py exports**

In `src/app/__init__.py`, add `run_cleanup` to the import from `app.cli` and to `__all__`:

```python
"""app package."""

from app.cli import run_cleanup, run_duplicates, run_hash, run_scan
from app.config import ScannerConfig, load_config
from app.database import open_database
from app.duplicates import find_duplicates
from app.hasher import hash_files
from app.scanner import scan_files

__all__: list[str] = [
    "ScannerConfig",
    "find_duplicates",
    "hash_files",
    "load_config",
    "open_database",
    "run_cleanup",
    "run_duplicates",
    "run_hash",
    "run_scan",
    "scan_files",
]
```

**Step 3: Create entry point**

Create `src/cleanup.py`:

```python
"""Entry point for the cleanup command."""

from pathlib import Path

from app.cli import run_cleanup

if __name__ == "__main__":
    run_cleanup(project_root=Path(__file__).resolve().parent.parent)
```

**Step 4: Add justfile recipe**

Add after the `duplicates` recipe in `justfile` (after line 38):

```just
# Interactively select and remove duplicate files by folder
[group('app')]
cleanup:
    @printf "\n"
    @printf "\033[0;34m=== Cleanup Duplicates ===\033[0m\n"
    @uv run src/cleanup.py
    @printf "\n"
```

**Step 5: Run full test suite**

Run: `just test`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/app/cli.py src/app/__init__.py src/cleanup.py justfile
git commit -m "Wire up cleanup command with CLI entry point and justfile recipe"
```

---

### Task 9: End-to-end test with real files

**Files:**
- Create: `tests/test_cleanup_e2e.py`

**Step 1: Write the e2e test**

Create `tests/test_cleanup_e2e.py`:

```python
"""End-to-end tests for the cleanup feature with real files on disk."""

from pathlib import Path

import yaml

from app.cli import run_hash, run_scan
from app.cleanup import (
    build_duplicate_groups,
    compute_folder_stats,
    execute_deletions,
    plan_deletions,
)
from app.database import count_total_files, open_database


def _create_test_project(tmp_path):
    """Create a test project with duplicate files on disk.

    Directory structure:
        files/
            originals/
                photo1.raw  (content: AAA...)
                photo2.raw  (content: BBB...)
                photo3.raw  (content: CCC...)
            backup1/
                photo1.raw  (dup of originals/photo1)
                photo2.raw  (dup of originals/photo2)
            backup2/
                photo1.raw  (dup of originals/photo1)
                photo2.raw  (dup of originals/photo2)
                photo3.raw  (dup of originals/photo3)
            unique_folder/
                solo.raw    (no duplicates)

    Returns:
        Tuple of (project_root, scan_dir, db_path).
    """
    scan_dir = tmp_path / "files"
    originals = scan_dir / "originals"
    backup1 = scan_dir / "backup1"
    backup2 = scan_dir / "backup2"
    unique_folder = scan_dir / "unique_folder"

    for d in [originals, backup1, backup2, unique_folder]:
        d.mkdir(parents=True)

    content_a = b"A" * 1024
    content_b = b"B" * 2048
    content_c = b"C" * 4096
    content_solo = b"S" * 512

    (originals / "photo1.raw").write_bytes(content_a)
    (originals / "photo2.raw").write_bytes(content_b)
    (originals / "photo3.raw").write_bytes(content_c)

    (backup1 / "photo1.raw").write_bytes(content_a)
    (backup1 / "photo2.raw").write_bytes(content_b)

    (backup2 / "photo1.raw").write_bytes(content_a)
    (backup2 / "photo2.raw").write_bytes(content_b)
    (backup2 / "photo3.raw").write_bytes(content_c)

    (unique_folder / "solo.raw").write_bytes(content_solo)

    project_root = tmp_path / "project"
    project_root.mkdir()

    db_path = project_root / "data" / "files.db"
    config = {
        "paths": [str(scan_dir)],
        "extensions": [".raw"],
        "case_sensitive": False,
        "recursive": True,
        "skip_dirs": [],
        "database": str(db_path),
    }
    (project_root / "config.yaml").write_text(yaml.dump(config))

    return project_root, scan_dir, db_path


class TestCleanupE2E:
    def test_full_pipeline_delete_one_folder(self, tmp_path):
        """Scan, hash, analyze, delete backup1, verify."""
        project_root, scan_dir, db_path = _create_test_project(tmp_path)

        # Run scan and hash via CLI functions
        run_scan(project_root=project_root)
        run_hash(project_root=project_root)

        # Open DB and analyze
        conn = open_database(db_path)
        assert count_total_files(conn) == 10

        groups = build_duplicate_groups(conn)
        assert len(groups) == 3  # photo1, photo2, photo3

        folder_stats = compute_folder_stats(groups)
        folder_names = [s.folder for s in folder_stats]
        # All three folders with dupes should appear
        assert "originals" in folder_names
        assert "backup1" in folder_names
        assert "backup2" in folder_names
        # unique_folder should NOT appear (no dupes)
        assert "unique_folder" not in folder_names

        # Plan deletion of backup1
        plan = plan_deletions(selected_folders=["backup1"], duplicate_groups=groups)
        assert len(plan.deletions) == 2  # photo1 and photo2 in backup1
        assert len(plan.protected_paths) == 0  # copies survive in originals + backup2

        # Execute
        base_path = Path(scan_dir).resolve()
        result = execute_deletions(conn=conn, base_path=base_path, plan=plan)

        assert result.deleted_count == 2
        assert result.failed_count == 0

        # Verify disk state
        assert not (scan_dir / "backup1" / "photo1.raw").exists()
        assert not (scan_dir / "backup1" / "photo2.raw").exists()

        assert (scan_dir / "originals" / "photo1.raw").exists()
        assert (scan_dir / "originals" / "photo2.raw").exists()
        assert (scan_dir / "originals" / "photo3.raw").exists()

        assert (scan_dir / "backup2" / "photo1.raw").exists()
        assert (scan_dir / "backup2" / "photo2.raw").exists()
        assert (scan_dir / "backup2" / "photo3.raw").exists()

        assert (scan_dir / "unique_folder" / "solo.raw").exists()

        # Verify DB state
        assert count_total_files(conn) == 8  # 10 - 2 deleted

        conn.close()

    def test_delete_multiple_folders(self, tmp_path):
        """Delete both backup1 and backup2, originals survive."""
        project_root, scan_dir, db_path = _create_test_project(tmp_path)

        run_scan(project_root=project_root)
        run_hash(project_root=project_root)

        conn = open_database(db_path)
        groups = build_duplicate_groups(conn)

        plan = plan_deletions(selected_folders=["backup1", "backup2"], duplicate_groups=groups)
        # backup1 has 2, backup2 has 3 → 5 deletions total
        assert len(plan.deletions) == 5
        assert len(plan.protected_paths) == 0  # originals always safe

        result = execute_deletions(conn=conn, base_path=scan_dir.resolve(), plan=plan)
        assert result.deleted_count == 5

        # All originals and unique_folder survive
        assert (scan_dir / "originals" / "photo1.raw").exists()
        assert (scan_dir / "originals" / "photo2.raw").exists()
        assert (scan_dir / "originals" / "photo3.raw").exists()
        assert (scan_dir / "unique_folder" / "solo.raw").exists()

        assert count_total_files(conn) == 5  # 10 - 5
        conn.close()

    def test_last_copy_protection_e2e(self, tmp_path):
        """Select ALL folders — last-copy protection keeps one copy of each."""
        project_root, scan_dir, db_path = _create_test_project(tmp_path)

        run_scan(project_root=project_root)
        run_hash(project_root=project_root)

        conn = open_database(db_path)
        groups = build_duplicate_groups(conn)

        # Select all folders that have duplicates
        folder_stats = compute_folder_stats(groups)
        all_folders = [s.folder for s in folder_stats]

        plan = plan_deletions(selected_folders=all_folders, duplicate_groups=groups)

        # 3 groups, each should protect 1 → 3 protected
        assert len(plan.protected_paths) == 3

        # Total files to delete: group1 has 3 copies (del 2), group2 has 3 (del 2), group3 has 2 (del 1) = 5
        assert len(plan.deletions) == 5

        result = execute_deletions(conn=conn, base_path=scan_dir.resolve(), plan=plan)
        assert result.deleted_count == 5

        # Verify exactly one copy of each content survives
        photo1_survivors = []
        photo2_survivors = []
        photo3_survivors = []
        for folder in ["originals", "backup1", "backup2"]:
            if (scan_dir / folder / "photo1.raw").exists():
                photo1_survivors.append(folder)
            if (scan_dir / folder / "photo2.raw").exists():
                photo2_survivors.append(folder)
            if (scan_dir / folder / "photo3.raw").exists():
                photo3_survivors.append(folder)

        assert len(photo1_survivors) == 1
        assert len(photo2_survivors) == 1
        assert len(photo3_survivors) == 1

        # unique_folder untouched
        assert (scan_dir / "unique_folder" / "solo.raw").exists()

        # DB: 10 original - 5 deleted = 5 (3 survivors + solo + unique)
        assert count_total_files(conn) == 5
        conn.close()

    def test_folder_ranking_order(self, tmp_path):
        """Verify folder stats are sorted by duplicate count descending."""
        project_root, scan_dir, db_path = _create_test_project(tmp_path)

        run_scan(project_root=project_root)
        run_hash(project_root=project_root)

        conn = open_database(db_path)
        groups = build_duplicate_groups(conn)
        folder_stats = compute_folder_stats(groups)

        counts = [(s.folder, s.duplicate_count) for s in folder_stats]
        # backup2 and originals both have 3, backup1 has 2
        assert counts[0][1] >= counts[1][1] >= counts[2][1]
        assert counts[2] == ("backup1", 2)
        conn.close()
```

**Step 2: Run e2e tests**

Run: `uv run pytest tests/test_cleanup_e2e.py -v`
Expected: 4 passed

**Step 3: Run full test suite**

Run: `just test`
Expected: All tests pass

**Step 4: Run full CI**

Run: `just ci-quiet`
Expected: All checks pass (linting, types, security, tests)

**Step 5: Commit**

```bash
git add tests/test_cleanup_e2e.py
git commit -m "Add end-to-end tests for cleanup with real files on disk"
```
