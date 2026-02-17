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
