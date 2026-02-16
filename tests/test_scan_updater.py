"""Tests for the scan_updater module."""

from unittest.mock import patch

from app.database import count_total_files, insert_file, open_database
from app.scan_updater import scan_update


class TestScanUpdate:
    def test_detects_and_deletes_missing_files(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = open_database(db_path)

        base_dir = tmp_path / "files"
        base_dir.mkdir()

        (base_dir / "exists.jpg").write_bytes(b"data")
        # "missing.jpg" is NOT created on disk

        insert_file(conn, "exists.jpg", "exists.jpg", ".jpg", 100)
        insert_file(conn, "missing.jpg", "missing.jpg", ".jpg", 200)
        conn.commit()

        assert count_total_files(conn) == 2

        with patch("builtins.input", return_value="y"):
            scan_update(conn=conn, base_path=base_dir)

        assert count_total_files(conn) == 1

        cursor = conn.execute("SELECT rel_path FROM files")
        remaining = [row[0] for row in cursor.fetchall()]
        assert remaining == ["exists.jpg"]

        conn.close()

    def test_all_files_exist(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = open_database(db_path)

        base_dir = tmp_path / "files"
        base_dir.mkdir()

        (base_dir / "a.jpg").write_bytes(b"aaa")
        (base_dir / "b.jpg").write_bytes(b"bbb")

        insert_file(conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(conn, "b.jpg", "b.jpg", ".jpg", 200)
        conn.commit()

        scan_update(conn=conn, base_path=base_dir)

        assert count_total_files(conn) == 2

        conn.close()

    def test_user_declines_deletion(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = open_database(db_path)

        base_dir = tmp_path / "files"
        base_dir.mkdir()

        # "gone.jpg" not created on disk
        insert_file(conn, "gone.jpg", "gone.jpg", ".jpg", 100)
        conn.commit()

        with patch("builtins.input", return_value="n"):
            scan_update(conn=conn, base_path=base_dir)

        assert count_total_files(conn) == 1

        conn.close()

    def test_empty_database(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = open_database(db_path)

        base_dir = tmp_path / "files"
        base_dir.mkdir()

        scan_update(conn=conn, base_path=base_dir)

        assert count_total_files(conn) == 0

        conn.close()
