"""Entry point for the cleanup command."""

from pathlib import Path

from app.cli import run_cleanup

if __name__ == "__main__":
    run_cleanup(project_root=Path(__file__).resolve().parent.parent)
