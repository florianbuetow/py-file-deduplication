"""Tests for the CLI module (end-to-end scan + hash + scan-update)."""

import sqlite3
from unittest.mock import patch

import yaml

from raw_deduplicator_v2.cli import run_hash, run_scan, run_scan_update
from raw_deduplicator_v2.database import count_total_files, count_unhashed_files


def _write_config(project_root, scan_dir, db_name="files.db"):
    config_path = project_root / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "paths": [str(scan_dir)],
                "extensions": [".jpg", ".png"],
                "case_sensitive": False,
                "recursive": True,
                "skip_dirs": [".git"],
                "database": str(project_root / "data" / db_name),
            }
        )
    )
    return config_path


class TestEndToEnd:
    def test_scan_then_hash(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        scan_dir = tmp_path / "files"
        scan_dir.mkdir()

        (scan_dir / "a.jpg").write_bytes(b"content aaa")
        (scan_dir / "b.png").write_bytes(b"content bbb")
        (scan_dir / "c.txt").write_text("should be ignored")

        _write_config(project_root, scan_dir)

        run_scan(project_root=project_root)

        db_path = project_root / "data" / "files.db"
        conn = sqlite3.connect(str(db_path))

        assert count_total_files(conn) == 2
        assert count_unhashed_files(conn) == 2

        conn.close()

        run_hash(project_root=project_root)

        conn = sqlite3.connect(str(db_path))

        assert count_unhashed_files(conn) == 0

        cursor = conn.execute("SELECT md5_hash, sha256_hash, hashed_at FROM files ORDER BY id")
        for row in cursor:
            assert row[0] is not None
            assert row[1] is not None
            assert row[2] is not None

        conn.close()

    def test_scan_is_idempotent(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        scan_dir = tmp_path / "files"
        scan_dir.mkdir()

        (scan_dir / "a.jpg").write_bytes(b"data")

        _write_config(project_root, scan_dir)

        run_scan(project_root=project_root)
        run_scan(project_root=project_root)

        db_path = project_root / "data" / "files.db"
        conn = sqlite3.connect(str(db_path))

        assert count_total_files(conn) == 1

        conn.close()

    def test_hash_is_idempotent(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        scan_dir = tmp_path / "files"
        scan_dir.mkdir()

        (scan_dir / "a.jpg").write_bytes(b"data")

        _write_config(project_root, scan_dir)

        run_scan(project_root=project_root)
        run_hash(project_root=project_root)
        run_hash(project_root=project_root)

        db_path = project_root / "data" / "files.db"
        conn = sqlite3.connect(str(db_path))

        assert count_unhashed_files(conn) == 0

        conn.close()

    def test_scan_with_subdirs_and_skip(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        scan_dir = tmp_path / "files"
        scan_dir.mkdir()

        subdir = scan_dir / "photos"
        subdir.mkdir()
        git_dir = scan_dir / ".git"
        git_dir.mkdir()

        (scan_dir / "root.jpg").write_bytes(b"data")
        (subdir / "nested.jpg").write_bytes(b"data")
        (git_dir / "hidden.jpg").write_bytes(b"data")

        _write_config(project_root, scan_dir)

        run_scan(project_root=project_root)

        db_path = project_root / "data" / "files.db"
        conn = sqlite3.connect(str(db_path))

        assert count_total_files(conn) == 2

        cursor = conn.execute("SELECT rel_path FROM files ORDER BY rel_path")
        paths = [row[0] for row in cursor.fetchall()]

        assert "photos/nested.jpg" in paths
        assert "root.jpg" in paths

        conn.close()

    def test_scan_update_removes_missing_files(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        scan_dir = tmp_path / "files"
        scan_dir.mkdir()

        (scan_dir / "keep.jpg").write_bytes(b"keep")
        (scan_dir / "delete.png").write_bytes(b"delete")

        _write_config(project_root, scan_dir)

        run_scan(project_root=project_root)

        db_path = project_root / "data" / "files.db"
        conn = sqlite3.connect(str(db_path))
        assert count_total_files(conn) == 2
        conn.close()

        # Remove one file from disk
        (scan_dir / "delete.png").unlink()

        with patch("builtins.input", return_value="y"):
            run_scan_update(project_root=project_root)

        conn = sqlite3.connect(str(db_path))
        assert count_total_files(conn) == 1

        cursor = conn.execute("SELECT rel_path FROM files")
        remaining = [row[0] for row in cursor.fetchall()]
        assert remaining == ["keep.jpg"]

        conn.close()
