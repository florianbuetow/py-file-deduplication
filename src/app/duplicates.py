"""Duplicate file finder for raw-deduplicator_v2.

Reads hashed file records from the SQLite database and identifies
groups of files that share identical file size, MD5, and SHA-256 hashes.
Reports duplicate counts and reclaimable disk space.
"""

import sqlite3
from collections import defaultdict

from app.database import iter_hashed_files

_GB: int = 1024**3
_MB: int = 1024**2
_KB: int = 1024


def _format_size(size: int) -> str:
    """Format a byte count with auto-selected unit."""
    if size >= _GB:
        return f"{size / _GB:.2f} GB"
    if size >= _MB:
        return f"{size / _MB:.2f} MB"
    if size >= _KB:
        return f"{size / _KB:.2f} KB"
    return f"{size} B"


def find_duplicates(conn: sqlite3.Connection) -> None:
    """Find and report duplicate files based on hashes stored in the database.

    Builds an in-memory index keyed by (file_size, md5_hash, sha256_hash).
    Files sharing the same key are duplicates. Reports the number of
    duplicate groups, their size distribution, and reclaimable space.

    Args:
        conn: An open SQLite connection to the files database.
    """
    print("Computing duplicates from database...")

    index: dict[str, set[str]] = defaultdict(set)
    total_hashed: int = 0

    cursor: sqlite3.Cursor = iter_hashed_files(conn)
    for row in cursor:
        file_size: int = row[0]
        md5_hash: str = row[1]
        sha256_hash: str = row[2]
        rel_path: str = row[3]

        key: str = f"{file_size}_{md5_hash}_{sha256_hash}"
        index[key].add(rel_path)
        total_hashed += 1

    print(f"Total hashed files analyzed: {total_hashed}")
    print()

    duplicate_groups: dict[str, set[str]] = {k: v for k, v in index.items() if len(v) > 1}

    total_duplicate_files: int = sum(len(paths) for paths in duplicate_groups.values())

    if total_duplicate_files == 0:
        print("No duplicates found.")
        return

    print(f"Duplicate files found: {total_duplicate_files}")
    print(f"Duplicate groups: {len(duplicate_groups)}")
    print()

    # Build distribution: how many groups have N duplicates
    size_distribution: dict[int, int] = defaultdict(int)
    for paths in duplicate_groups.values():
        size_distribution[len(paths)] += 1

    print("Distribution:")
    for count in sorted(size_distribution.keys()):
        groups: int = size_distribution[count]
        label: str = "group" if groups == 1 else "groups"
        copies: str = "copy" if count == 1 else "copies"
        print(f"  {groups} {label} with {count} {copies} each")

    print()

    # Compute reclaimable space
    # For each group, we keep 1 file and can reclaim (N-1) * file_size
    reclaimable_bytes: int = 0
    for key, paths in duplicate_groups.items():
        file_size_str: str = key.split("_")[0]
        file_size_val: int = int(file_size_str)
        reclaimable_bytes += (len(paths) - 1) * file_size_val

    print(f"Reclaimable space: {_format_size(reclaimable_bytes)}")
