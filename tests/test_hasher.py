"""Tests for the hasher module."""

import hashlib

import pytest

from raw_deduplicator_v2.database import (
    count_unhashed_files,
    insert_file,
    open_database,
)
from raw_deduplicator_v2.hasher import hash_files


@pytest.fixture()
def db_conn(tmp_path):
    db_path = tmp_path / "test.db"
    conn = open_database(db_path)
    yield conn
    conn.close()


class TestHashFiles:
    def test_hashes_all_unhashed_files(self, tmp_path, db_conn):
        file_a = tmp_path / "a.jpg"
        file_b = tmp_path / "b.jpg"
        file_a.write_text("content a")
        file_b.write_text("content b")

        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 9)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 9)
        db_conn.commit()

        hash_files(conn=db_conn, base_path=tmp_path)

        assert count_unhashed_files(db_conn) == 0

    def test_computes_correct_md5(self, tmp_path, db_conn):
        content = b"hello world"
        file_path = tmp_path / "test.jpg"
        file_path.write_bytes(content)
        expected_md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()

        insert_file(db_conn, "test.jpg", "test.jpg", ".jpg", len(content))
        db_conn.commit()

        hash_files(conn=db_conn, base_path=tmp_path)

        cursor = db_conn.execute("SELECT md5_hash FROM files WHERE id = 1")
        actual_md5 = cursor.fetchone()[0]

        assert actual_md5 == expected_md5

    def test_computes_correct_sha256(self, tmp_path, db_conn):
        content = b"hello world"
        file_path = tmp_path / "test.jpg"
        file_path.write_bytes(content)
        expected_sha256 = hashlib.sha256(content).hexdigest()

        insert_file(db_conn, "test.jpg", "test.jpg", ".jpg", len(content))
        db_conn.commit()

        hash_files(conn=db_conn, base_path=tmp_path)

        cursor = db_conn.execute("SELECT sha256_hash FROM files WHERE id = 1")
        actual_sha256 = cursor.fetchone()[0]

        assert actual_sha256 == expected_sha256

    def test_sets_hashed_at_timestamp(self, tmp_path, db_conn):
        (tmp_path / "test.jpg").write_text("data")

        insert_file(db_conn, "test.jpg", "test.jpg", ".jpg", 4)
        db_conn.commit()

        hash_files(conn=db_conn, base_path=tmp_path)

        cursor = db_conn.execute("SELECT hashed_at FROM files WHERE id = 1")
        hashed_at = cursor.fetchone()[0]

        assert hashed_at is not None
        assert "T" in hashed_at  # ISO format

    def test_skips_already_hashed_files(self, tmp_path, db_conn):
        (tmp_path / "a.jpg").write_text("data a")
        (tmp_path / "b.jpg").write_text("data b")

        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 6)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 6)
        db_conn.commit()

        # Hash only file a
        hash_files(conn=db_conn, base_path=tmp_path)

        # Get hash for file a
        cursor = db_conn.execute("SELECT md5_hash FROM files WHERE id = 1")
        first_hash = cursor.fetchone()[0]

        # Run again — should not re-hash
        hash_files(conn=db_conn, base_path=tmp_path)

        cursor = db_conn.execute("SELECT md5_hash FROM files WHERE id = 1")
        second_hash = cursor.fetchone()[0]

        assert first_hash == second_hash

    def test_nothing_to_hash_message(self, tmp_path, db_conn, capsys):
        hash_files(conn=db_conn, base_path=tmp_path)

        captured = capsys.readouterr()
        assert "Nothing to hash" in captured.out


class TestHashFilesErrorHandling:
    def test_skips_missing_file(self, tmp_path, db_conn, capsys):
        insert_file(db_conn, "gone.jpg", "gone.jpg", ".jpg", 100)
        db_conn.commit()

        hash_files(conn=db_conn, base_path=tmp_path)

        assert count_unhashed_files(db_conn) == 1

        captured = capsys.readouterr()
        assert "WARNING" in captured.err

    def test_continues_after_error(self, tmp_path, db_conn):
        (tmp_path / "good.jpg").write_text("data")

        insert_file(db_conn, "gone.jpg", "gone.jpg", ".jpg", 100)
        insert_file(db_conn, "good.jpg", "good.jpg", ".jpg", 4)
        db_conn.commit()

        hash_files(conn=db_conn, base_path=tmp_path)

        # gone.jpg still unhashed, good.jpg was hashed
        assert count_unhashed_files(db_conn) == 1

        cursor = db_conn.execute("SELECT md5_hash FROM files WHERE rel_path = 'good.jpg'")
        assert cursor.fetchone()[0] is not None


class TestHashFilesProgress:
    def test_prints_progress_for_each_file(self, tmp_path, db_conn, capsys):
        (tmp_path / "a.jpg").write_text("data")
        (tmp_path / "b.jpg").write_text("data")

        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 4)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 4)
        db_conn.commit()

        hash_files(conn=db_conn, base_path=tmp_path)

        captured = capsys.readouterr()
        assert "[1/2]" in captured.out
        assert "[2/2]" in captured.out
        assert "100.00%" in captured.out
