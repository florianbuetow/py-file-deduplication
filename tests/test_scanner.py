"""Tests for the scanner module."""

import pytest

from raw_deduplicator_v2.config import ScannerConfig
from raw_deduplicator_v2.database import count_total_files, open_database
from raw_deduplicator_v2.scanner import scan_files


@pytest.fixture()
def db_conn(tmp_path):
    db_path = tmp_path / "test.db"
    conn = open_database(db_path)
    yield conn
    conn.close()


def _make_config(scan_path, **overrides):
    defaults = {
        "paths": [str(scan_path)],
        "extensions": [".jpg", ".png"],
        "case_sensitive": False,
        "recursive": True,
        "skip_dirs": [],
        "database": "unused.db",
    }
    defaults.update(overrides)
    return ScannerConfig(**defaults)


class TestScanFindsFiles:
    def test_finds_matching_files(self, tmp_path, db_conn):
        (tmp_path / "photo.jpg").write_text("data")
        (tmp_path / "image.png").write_text("data")
        (tmp_path / "readme.txt").write_text("data")

        config = _make_config(tmp_path)
        scan_files(config=config, conn=db_conn)

        assert count_total_files(db_conn) == 2

    def test_finds_files_recursively(self, tmp_path, db_conn):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "a.jpg").write_text("data")
        (subdir / "b.jpg").write_text("data")

        config = _make_config(tmp_path)
        scan_files(config=config, conn=db_conn)

        assert count_total_files(db_conn) == 2

    def test_non_recursive_skips_subdirs(self, tmp_path, db_conn):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "a.jpg").write_text("data")
        (subdir / "b.jpg").write_text("data")

        config = _make_config(tmp_path, recursive=False)
        scan_files(config=config, conn=db_conn)

        assert count_total_files(db_conn) == 1


class TestScanCaseSensitivity:
    def test_case_insensitive_matches_uppercase(self, tmp_path, db_conn):
        (tmp_path / "photo.JPG").write_text("data")

        config = _make_config(tmp_path, case_sensitive=False)
        scan_files(config=config, conn=db_conn)

        assert count_total_files(db_conn) == 1

    def test_case_sensitive_skips_mismatched_case(self, tmp_path, db_conn):
        (tmp_path / "photo.JPG").write_text("data")

        config = _make_config(tmp_path, case_sensitive=True, extensions=[".jpg"])
        scan_files(config=config, conn=db_conn)

        assert count_total_files(db_conn) == 0


class TestScanSkipDirs:
    def test_skips_configured_dirs(self, tmp_path, db_conn):
        skip_dir = tmp_path / "node_modules"
        skip_dir.mkdir()
        (skip_dir / "a.jpg").write_text("data")
        (tmp_path / "b.jpg").write_text("data")

        config = _make_config(tmp_path, skip_dirs=["node_modules"])
        scan_files(config=config, conn=db_conn)

        assert count_total_files(db_conn) == 1

    def test_skips_dot_prefixed_dirs(self, tmp_path, db_conn):
        dot_dir = tmp_path / ".hidden"
        dot_dir.mkdir()
        (dot_dir / "a.jpg").write_text("data")
        (tmp_path / "b.jpg").write_text("data")

        config = _make_config(tmp_path)
        scan_files(config=config, conn=db_conn)

        assert count_total_files(db_conn) == 1

    def test_skips_dot_prefixed_files(self, tmp_path, db_conn):
        (tmp_path / ".hidden.jpg").write_text("data")
        (tmp_path / "visible.jpg").write_text("data")

        config = _make_config(tmp_path)
        scan_files(config=config, conn=db_conn)

        assert count_total_files(db_conn) == 1


class TestScanRelPaths:
    def test_stores_relative_path(self, tmp_path, db_conn):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (subdir / "photo.jpg").write_text("data")

        config = _make_config(tmp_path)
        scan_files(config=config, conn=db_conn)

        cursor = db_conn.execute("SELECT rel_path FROM files")
        rel_path = cursor.fetchone()[0]

        assert rel_path == "sub/photo.jpg"


class TestScanIdempotency:
    def test_does_not_insert_duplicates(self, tmp_path, db_conn):
        (tmp_path / "photo.jpg").write_text("data")

        config = _make_config(tmp_path)
        scan_files(config=config, conn=db_conn)
        scan_files(config=config, conn=db_conn)

        assert count_total_files(db_conn) == 1


class TestScanMissingPath:
    def test_handles_nonexistent_path(self, tmp_path, db_conn):
        config = _make_config(tmp_path / "nonexistent")
        scan_files(config=config, conn=db_conn)

        assert count_total_files(db_conn) == 0


class TestScanProgressOutput:
    def test_prints_file_count_and_current_folder(self, tmp_path, db_conn, capsys):
        subdir = tmp_path / "photos"
        subdir.mkdir()
        (tmp_path / "a.jpg").write_text("data")
        (subdir / "b.jpg").write_text("data")

        config = _make_config(tmp_path)
        scan_files(config=config, conn=db_conn)

        captured = capsys.readouterr()
        assert "[0 files found]" in captured.out
        assert "[1 files found]" in captured.out

    def test_prints_scanning_folder_name(self, tmp_path, db_conn, capsys):
        subdir = tmp_path / "photos"
        subdir.mkdir()
        (subdir / "a.jpg").write_text("data")

        config = _make_config(tmp_path)
        scan_files(config=config, conn=db_conn)

        captured = capsys.readouterr()
        assert "Scanning" in captured.out
        assert "photos" in captured.out


class TestScanFileMetadata:
    def test_stores_filename_and_extension(self, tmp_path, db_conn):
        (tmp_path / "photo.jpg").write_text("some content")

        config = _make_config(tmp_path)
        scan_files(config=config, conn=db_conn)

        cursor = db_conn.execute("SELECT filename, extension, file_size FROM files")
        row = cursor.fetchone()

        assert row[0] == "photo.jpg"
        assert row[1] == ".jpg"
        assert row[2] == 12  # len("some content")
