"""Entry point for the hash command."""

from pathlib import Path

from raw_deduplicator_v2.cli import run_hash

if __name__ == "__main__":
    run_hash(project_root=Path(__file__).resolve().parent.parent)
