"""Entry point for the scan-update command."""

from pathlib import Path

from raw_deduplicator_v2.cli import run_scan_update

if __name__ == "__main__":
    run_scan_update(project_root=Path(__file__).resolve().parent.parent)
