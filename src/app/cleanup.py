"""Interactive duplicate folder cleanup for raw-deduplicator_v2.

Analyzes duplicate files by folder, provides an interactive TUI for
selecting which folders' duplicates to remove, and executes deletion
with last-copy safety protection.
"""

import dataclasses
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath

from app.database import delete_files, iter_hashed_files_with_id

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
