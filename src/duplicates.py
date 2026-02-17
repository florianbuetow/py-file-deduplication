"""Entry point for the duplicates command."""

from pathlib import Path

from app.cli import run_duplicates

if __name__ == "__main__":
    run_duplicates(project_root=Path(__file__).resolve().parent.parent)
