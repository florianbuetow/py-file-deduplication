"""CLI entry points for raw-deduplicator_v2."""

import sqlite3
import sys
from pathlib import Path

from app.cleanup import run_cleanup_interactive
from app.config import ScannerConfig, load_config
from app.database import open_database
from app.duplicates import find_duplicates
from app.hasher import hash_files
from app.scan_updater import scan_update
from app.scanner import scan_files


def _resolve_config_and_db(project_root: Path) -> tuple[ScannerConfig, sqlite3.Connection, Path]:
    """Load config and open the database connection.

    Args:
        project_root: Absolute path to the project root directory.

    Returns:
        A tuple of (config, db_connection, resolved_db_path).
    """
    config_path: Path = project_root / "config.yaml"
    config: ScannerConfig = load_config(config_path)

    db_path: Path = Path(config.database)
    if not db_path.is_absolute():
        db_path = project_root / db_path

    conn: sqlite3.Connection = open_database(db_path)
    return config, conn, db_path


def run_scan(project_root: Path) -> None:
    """Run the file scanning pass.

    Loads config, opens the database, crawls configured directories,
    and inserts discovered files into the database.

    Args:
        project_root: Absolute path to the project root directory.
    """
    config, conn, db_path = _resolve_config_and_db(project_root)
    print(f"Database: {db_path}")
    print("")

    try:
        scan_files(config=config, conn=conn)
    finally:
        conn.close()


def run_hash(project_root: Path) -> None:
    """Run the file hashing pass.

    Loads config, opens the database, and computes MD5 + SHA-256
    hashes for all unhashed file records.

    Args:
        project_root: Absolute path to the project root directory.
    """
    config, conn, db_path = _resolve_config_and_db(project_root)
    print(f"Database: {db_path}")
    print("")

    if len(config.paths) != 1:
        print("ERROR: Hashing requires exactly one scan path to resolve relative paths.", file=sys.stderr)
        conn.close()
        sys.exit(1)

    base_path: Path = Path(config.paths[0]).resolve()

    try:
        hash_files(conn=conn, base_path=base_path)
    finally:
        conn.close()


def run_scan_update(project_root: Path) -> None:
    """Run the scan-update pass.

    Loads config, opens the database, and checks all file records
    against disk, removing entries for files that no longer exist.

    Args:
        project_root: Absolute path to the project root directory.
    """
    config, conn, db_path = _resolve_config_and_db(project_root)
    print(f"Database: {db_path}")
    print("")

    if len(config.paths) != 1:
        print("ERROR: Scan-update requires exactly one scan path to resolve relative paths.", file=sys.stderr)
        conn.close()
        sys.exit(1)

    base_path: Path = Path(config.paths[0]).resolve()

    try:
        scan_update(conn=conn, base_path=base_path)
    finally:
        conn.close()


def run_duplicates(project_root: Path) -> None:
    """Run the duplicate file finder.

    Loads config, opens the database, and identifies duplicate files
    based on matching file size, MD5, and SHA-256 hashes.

    Args:
        project_root: Absolute path to the project root directory.
    """
    _config, conn, db_path = _resolve_config_and_db(project_root)
    print(f"Database: {db_path}")
    print("")

    try:
        find_duplicates(conn=conn)
    finally:
        conn.close()


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
