"""File hasher for raw-deduplicator_v2.

Iterates over unhashed file records in the SQLite database,
computes full-file MD5 and SHA-256 hashes, and updates the database.
"""

import hashlib
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from app.database import count_total_files, count_unhashed_files, iter_unhashed_files, sum_unhashed_bytes, update_hashes

_HASH_BUFFER_SIZE: int = 65536
_GB: int = 1024**3
_MB: int = 1024**2
_KB: int = 1024


def _format_size_single(size: int) -> str:
    """Format a byte count with auto-selected unit."""
    if size >= _GB:
        return f"{int(size / _GB)} GB"
    if size >= _MB:
        return f"{int(size / _MB)} MB"
    if size >= _KB:
        return f"{int(size / _KB)} KB"
    return f"{size} B"


def _format_size_pair(done: int, total: int) -> str:
    """Format a done/total byte pair with auto-selected unit on the total only."""
    if total >= _GB:
        return f"{int(done / _GB)}/{int(total / _GB)} GB"
    if total >= _MB:
        return f"{int(done / _MB)}/{int(total / _MB)} MB"
    if total >= _KB:
        return f"{int(done / _KB)}/{int(total / _KB)} KB"
    return f"{done}/{total} B"


def hash_files(conn: sqlite3.Connection, base_path: Path) -> None:
    """Compute MD5 and SHA-256 hashes for all unhashed files in the database.

    Iterates over files that don't yet have hashes computed, reads each
    file from disk, computes both MD5 and SHA-256 full-file hashes, and
    updates the database. Prints progress for each file processed.

    Files that cannot be read (missing, permission denied, etc.) are
    skipped with a warning and left unhashed for a future retry.

    Args:
        conn: An open SQLite connection to the files database.
        base_path: The resolved base directory that rel_path values are relative to.
    """
    total_in_db: int = count_total_files(conn)
    unhashed_count: int = count_unhashed_files(conn)
    already_hashed: int = total_in_db - unhashed_count

    print(f"Total files in database: {total_in_db}")
    print(f"Already hashed: {already_hashed}")
    print(f"Files to hash: {unhashed_count}")

    total_bytes: int = sum_unhashed_bytes(conn)
    print(f"Bytes to hash: {_format_size_single(total_bytes)}")
    print()

    if unhashed_count == 0:
        print("Nothing to hash.")
        return

    hashed_count: int = 0
    failed_count: int = 0
    current: int = 0
    bytes_processed: int = 0
    start_time: float = time.monotonic()

    cursor: sqlite3.Cursor = iter_unhashed_files(conn)

    for row in cursor:
        file_id: int = row[0]
        rel_path: str = row[1]
        file_size: int = row[2]
        full_path: Path = base_path / rel_path

        current = current + 1
        pct: float = (current * 100.0) / unhashed_count

        eta_str: str = ""
        files_done: int = current - 1
        if files_done > 0:
            elapsed: float = time.monotonic() - start_time
            remaining_seconds: int = int(elapsed * (unhashed_count - files_done) / files_done)
            eta_hours: int = remaining_seconds // 3600
            eta_minutes: int = (remaining_seconds % 3600) // 60
            eta_str = f" [ETA {eta_hours}h{eta_minutes:02d}m]"

        size_str: str = f"[{_format_size_pair(bytes_processed, total_bytes)}]"
        print(f"[{current}/{unhashed_count}] {size_str} [{pct:.2f}%]{eta_str} Hashing ... {rel_path}")

        try:
            md5_hex, sha256_hex = _compute_file_hashes(full_path)
        except (FileNotFoundError, PermissionError, OSError) as err:
            print(f"  WARNING: Could not hash {full_path}: {err}", file=sys.stderr)
            failed_count = failed_count + 1
            continue

        hashed_at: str = datetime.now(tz=UTC).isoformat()

        update_hashes(
            conn=conn,
            file_id=file_id,
            md5_hash=md5_hex,
            sha256_hash=sha256_hex,
            hashed_at=hashed_at,
        )

        hashed_count = hashed_count + 1
        bytes_processed = bytes_processed + file_size

        if hashed_count % 100 == 0:
            conn.commit()

    conn.commit()

    print("\nHashing complete.")
    print(f"  Hashed: {hashed_count}")
    print(f"  Failed: {failed_count}")
    print(f"  Previously hashed: {already_hashed}")


def _compute_file_hashes(file_path: Path) -> tuple[str, str]:
    """Compute the full-file MD5 and SHA-256 hashes simultaneously.

    Reads the file in chunks and feeds each chunk to both hash
    algorithms in a single pass for efficiency.

    Args:
        file_path: Absolute path to the file to hash.

    Returns:
        A tuple of (md5_hex, sha256_hex) hash strings.

    Raises:
        FileNotFoundError: If the file does not exist.
        PermissionError: If the file cannot be read.
        OSError: If an I/O error occurs.
    """
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as f:
        while True:
            chunk: bytes = f.read(_HASH_BUFFER_SIZE)
            if not chunk:
                break
            md5.update(chunk)
            sha256.update(chunk)

    return md5.hexdigest(), sha256.hexdigest()
