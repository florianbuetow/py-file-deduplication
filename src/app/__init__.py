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
