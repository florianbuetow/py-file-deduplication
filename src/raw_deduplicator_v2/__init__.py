"""raw_deduplicator_v2 package."""

from raw_deduplicator_v2.cli import run_hash, run_scan
from raw_deduplicator_v2.config import ScannerConfig, load_config
from raw_deduplicator_v2.database import open_database
from raw_deduplicator_v2.hasher import hash_files
from raw_deduplicator_v2.scanner import scan_files

__all__: list[str] = [
    "ScannerConfig",
    "hash_files",
    "load_config",
    "open_database",
    "run_hash",
    "run_scan",
    "scan_files",
]
