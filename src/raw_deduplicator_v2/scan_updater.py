"""Scan updater for raw-deduplicator_v2.

Iterates over all file records in the SQLite database, checks whether
each file still exists on disk, and removes stale entries after user
confirmation.
"""

import sqlite3
from pathlib import Path

from raw_deduplicator_v2.database import count_total_files, delete_files, iter_all_files


def scan_update(conn: sqlite3.Connection, base_path: Path) -> None:
    """Check all database entries against disk and remove missing files.

    Iterates every file record, verifies the file still exists at
    base_path / rel_path, collects IDs of missing files, and after
    user confirmation deletes them from the database.

    Args:
        conn: An open SQLite connection to the files database.
        base_path: The resolved base directory that rel_path values are relative to.
    """
    total: int = count_total_files(conn)
    print(f"Total files in database: {total}")
    print()

    if total == 0:
        print("Nothing to check.")
        return

    missing_ids: list[int] = []
    current: int = 0

    cursor: sqlite3.Cursor = iter_all_files(conn)

    for row in cursor:
        file_id: int = row[0]
        rel_path: str = row[1]
        full_path: Path = base_path / rel_path

        current = current + 1
        print(f"[{current}/{total}] Checking ... {full_path}")

        if not full_path.exists():
            missing_ids.append(file_id)

    missing_count: int = len(missing_ids)
    print()
    print(f"Missing files: {missing_count}")

    if missing_count == 0:
        print("All files accounted for.")
        return

    answer: str = input(f"Delete {missing_count} files from database? [y/N] ")
    if answer.strip().lower() != "y":
        print("Aborted. No files deleted.")
        return

    deleted: int = delete_files(conn, missing_ids)
    conn.commit()
    print(f"Deleted {deleted} files from database.")
