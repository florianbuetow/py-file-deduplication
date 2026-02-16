"""File scanner for raw-deduplicator_v2.

Crawls configured directories, discovers files matching configured
extensions, and inserts them into the SQLite database.
"""

import os
import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path

from raw_deduplicator_v2.config import ScannerConfig
from raw_deduplicator_v2.database import count_total_files, insert_file


def scan_files(config: ScannerConfig, conn: sqlite3.Connection) -> None:
    """Scan configured directories and insert discovered files into the database.

    For each configured path, crawls the directory tree (respecting
    skip_dirs, extensions, case_sensitive, and recursive settings)
    and inserts each discovered file into the database. Files already
    in the database (by rel_path) are silently skipped.

    Args:
        config: The validated scanner configuration.
        conn: An open SQLite connection to the files database.
    """
    total_inserted: int = 0
    total_skipped: int = 0
    total_errors: int = 0

    for scan_path_str in config.paths:
        scan_root: Path = Path(scan_path_str).resolve()

        if not scan_root.exists():
            print(f"WARNING: Path does not exist, skipping: {scan_root}")
            total_errors = total_errors + 1
            continue

        if not scan_root.is_dir():
            print(f"WARNING: Path is not a directory, skipping: {scan_root}")
            total_errors = total_errors + 1
            continue

        print(f"Scanning: {scan_root}")

        inserted: int = 0
        skipped: int = 0
        current_dir: str = ""

        for file_path in _crawl_directory(
            root=scan_root,
            extensions=config.extensions,
            case_sensitive=config.case_sensitive,
            recursive=config.recursive,
            skip_dirs=config.skip_dirs,
        ):
            parent_rel: str = str(file_path.parent.relative_to(scan_root))
            if parent_rel != current_dir:
                current_dir = parent_rel
                found: int = inserted + skipped
                display_dir: str = current_dir if current_dir != "." else str(scan_root)
                print(f"[{found} files found] Scanning ... {display_dir}")
                sys.stdout.flush()

            rel_path: str = str(file_path.relative_to(scan_root))
            filename: str = file_path.name
            extension: str = file_path.suffix
            if not config.case_sensitive:
                extension = extension.lower()

            try:
                file_size: int = file_path.stat().st_size
            except OSError as err:
                print(f"  WARNING: Could not stat {file_path}: {err}")
                total_errors = total_errors + 1
                continue

            was_inserted: bool = insert_file(
                conn=conn,
                filename=filename,
                rel_path=rel_path,
                extension=extension,
                file_size=file_size,
            )

            if was_inserted:
                inserted = inserted + 1
            else:
                skipped = skipped + 1

        conn.commit()
        total_inserted = total_inserted + inserted
        total_skipped = total_skipped + skipped
        print(f"  Inserted: {inserted}, Already in DB: {skipped}")

    total_in_db: int = count_total_files(conn)

    print("\nScan complete.")
    print(f"  New files added: {total_inserted}")
    print(f"  Already in DB: {total_skipped}")
    print(f"  Errors: {total_errors}")
    print(f"  Total files in database: {total_in_db}")


def _crawl_directory(
    root: Path,
    extensions: list[str],
    case_sensitive: bool,
    recursive: bool,
    skip_dirs: list[str],
) -> Iterator[Path]:
    """Crawl a directory tree for files matching given extensions.

    Does NOT follow symlinks. Skips directories whose names start
    with a dot or appear in the skip_dirs list.

    Args:
        root: The resolved root directory to crawl.
        extensions: List of file extensions with dots (e.g., [".jpg"]).
        case_sensitive: Whether extension matching is case sensitive.
        recursive: Whether to descend into subdirectories.
        skip_dirs: List of directory names to skip.

    Yields:
        Absolute Path objects for each matching file.
    """
    skip_set: set[str] = set(skip_dirs)

    if case_sensitive:
        ext_set: set[str] = set(extensions)
    else:
        ext_set = {e.lower() for e in extensions}

    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in skip_set]

        for filename in filenames:
            if filename.startswith("."):
                continue
            file_ext: str = os.path.splitext(filename)[1]
            if not case_sensitive:
                file_ext = file_ext.lower()
            if file_ext in ext_set:
                yield Path(dirpath) / filename

        if not recursive:
            dirnames.clear()
