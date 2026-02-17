"""Entry point for the cleanup command."""

import sys
from pathlib import Path

from app.cli import run_cleanup

if __name__ == "__main__":
    force: bool = "--force" in sys.argv
    run_cleanup(project_root=Path(__file__).resolve().parent.parent, force=force)
