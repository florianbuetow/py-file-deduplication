"""SQLite database operations for raw-deduplicator_v2."""

import sqlite3
from pathlib import Path


def open_database(db_path: Path) -> sqlite3.Connection:
    """Open a connection to the SQLite database, creating it if needed.

    Creates the parent directory if it does not exist. Initializes
    the schema (table + indexes) on first use.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        An open sqlite3.Connection with WAL journal mode enabled.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn: sqlite3.Connection = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    _create_schema(conn)
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create the files table and indexes if they don't exist.

    Args:
        conn: An open SQLite connection.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            rel_path TEXT NOT NULL UNIQUE,
            extension TEXT NOT NULL,
            md5_hash TEXT,
            sha256_hash TEXT,
            file_size INTEGER NOT NULL,
            hashed_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_md5_hash ON files (md5_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_sha256_hash ON files (sha256_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_file_size ON files (file_size)")
    conn.commit()


def insert_file(
    conn: sqlite3.Connection,
    filename: str,
    rel_path: str,
    extension: str,
    file_size: int,
) -> bool:
    """Insert a file record into the database if it doesn't already exist.

    Uses INSERT OR IGNORE to skip files whose rel_path already exists
    (enforced by the UNIQUE constraint).

    Args:
        conn: An open SQLite connection.
        filename: The base filename (e.g., "photo.jpg").
        rel_path: The relative path from the scan root (e.g., "subdir/photo.jpg").
        extension: The file extension including dot (e.g., ".jpg").
        file_size: The file size in bytes.

    Returns:
        True if the file was inserted, False if it already existed.
    """
    cursor: sqlite3.Cursor = conn.execute(
        """
        INSERT OR IGNORE INTO files (filename, rel_path, extension, file_size)
        VALUES (?, ?, ?, ?)
        """,
        (filename, rel_path, extension, file_size),
    )
    return cursor.rowcount > 0


def count_total_files(conn: sqlite3.Connection) -> int:
    """Count the total number of files in the database.

    Args:
        conn: An open SQLite connection.

    Returns:
        The total number of file records.
    """
    cursor: sqlite3.Cursor = conn.execute("SELECT COUNT(*) FROM files")
    row: tuple[int] = cursor.fetchone()
    return row[0]


def count_unhashed_files(conn: sqlite3.Connection) -> int:
    """Count files that have not yet been hashed.

    Args:
        conn: An open SQLite connection.

    Returns:
        The number of file records with NULL md5_hash.
    """
    cursor: sqlite3.Cursor = conn.execute("SELECT COUNT(*) FROM files WHERE md5_hash IS NULL")
    row: tuple[int] = cursor.fetchone()
    return row[0]


def iter_unhashed_files(conn: sqlite3.Connection) -> sqlite3.Cursor:
    """Return a cursor over all unhashed file records.

    Yields rows as (id, rel_path, file_size) for files that have not
    yet been hashed (md5_hash IS NULL).

    Args:
        conn: An open SQLite connection.

    Returns:
        A cursor iterating over (id, rel_path, file_size) tuples.
    """
    return conn.execute("SELECT id, rel_path, file_size FROM files WHERE md5_hash IS NULL ORDER BY id")


def update_hashes(
    conn: sqlite3.Connection,
    file_id: int,
    md5_hash: str,
    sha256_hash: str,
    hashed_at: str,
) -> None:
    """Update the hash columns for a specific file record.

    Args:
        conn: An open SQLite connection.
        file_id: The row ID of the file to update.
        md5_hash: The computed MD5 hash hex string.
        sha256_hash: The computed SHA-256 hash hex string.
        hashed_at: ISO-8601 timestamp of when the hash was computed.
    """
    conn.execute(
        """
        UPDATE files
        SET md5_hash = ?, sha256_hash = ?, hashed_at = ?
        WHERE id = ?
        """,
        (md5_hash, sha256_hash, hashed_at, file_id),
    )
