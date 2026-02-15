"""Entry point for the scan command."""

from pathlib import Path

from raw_deduplicator_v2.cli import run_scan

if __name__ == "__main__":
    run_scan(project_root=Path(__file__).resolve().parent.parent)
