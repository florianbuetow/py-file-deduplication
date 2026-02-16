"""Tests for the database module."""

import pytest

from raw_deduplicator_v2.database import (
    count_total_files,
    count_unhashed_files,
    delete_files,
    insert_file,
    iter_all_files,
    iter_unhashed_files,
    open_database,
    update_hashes,
)


@pytest.fixture()
def db_conn(tmp_path):
    db_path = tmp_path / "test.db"
    conn = open_database(db_path)
    yield conn
    conn.close()


class TestOpenDatabase:
    def test_creates_database_file(self, tmp_path):
        db_path = tmp_path / "subdir" / "test.db"
        conn = open_database(db_path)

        assert db_path.exists()
        conn.close()

    def test_creates_files_table(self, db_conn):
        cursor = db_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='files'")
        assert cursor.fetchone() is not None

    def test_creates_indexes(self, db_conn):
        cursor = db_conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_files_%'")
        index_names = {row[0] for row in cursor.fetchall()}

        assert "idx_files_md5_hash" in index_names
        assert "idx_files_sha256_hash" in index_names
        assert "idx_files_file_size" in index_names

    def test_uses_wal_journal_mode(self, db_conn):
        cursor = db_conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal"


class TestInsertFile:
    def test_inserts_new_file(self, db_conn):
        result = insert_file(
            conn=db_conn,
            filename="photo.jpg",
            rel_path="subdir/photo.jpg",
            extension=".jpg",
            file_size=1024,
        )

        assert result is True

    def test_returns_false_for_duplicate_rel_path(self, db_conn):
        insert_file(db_conn, "photo.jpg", "subdir/photo.jpg", ".jpg", 1024)
        db_conn.commit()

        result = insert_file(db_conn, "photo.jpg", "subdir/photo.jpg", ".jpg", 1024)

        assert result is False

    def test_stores_correct_values(self, db_conn):
        insert_file(db_conn, "photo.jpg", "subdir/photo.jpg", ".jpg", 2048)
        db_conn.commit()

        cursor = db_conn.execute("SELECT id, filename, rel_path, extension, md5_hash, sha256_hash, file_size, hashed_at FROM files")
        row = cursor.fetchone()

        assert row[0] == 1  # auto-increment id
        assert row[1] == "photo.jpg"
        assert row[2] == "subdir/photo.jpg"
        assert row[3] == ".jpg"
        assert row[4] is None  # md5_hash not yet set
        assert row[5] is None  # sha256_hash not yet set
        assert row[6] == 2048
        assert row[7] is None  # hashed_at not yet set

    def test_autoincrement_ids(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 200)
        db_conn.commit()

        cursor = db_conn.execute("SELECT id FROM files ORDER BY id")
        ids = [row[0] for row in cursor.fetchall()]

        assert ids == [1, 2]


class TestCountFunctions:
    def test_count_total_files_empty(self, db_conn):
        assert count_total_files(db_conn) == 0

    def test_count_total_files_with_data(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 200)
        db_conn.commit()

        assert count_total_files(db_conn) == 2

    def test_count_unhashed_files_all_unhashed(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 200)
        db_conn.commit()

        assert count_unhashed_files(db_conn) == 2

    def test_count_unhashed_files_some_hashed(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 200)
        db_conn.commit()

        update_hashes(db_conn, 1, "md5abc", "sha256abc", "2026-01-01T00:00:00Z")
        db_conn.commit()

        assert count_unhashed_files(db_conn) == 1


class TestIterUnhashedFiles:
    def test_returns_only_unhashed(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 200)
        insert_file(db_conn, "c.jpg", "c.jpg", ".jpg", 300)
        db_conn.commit()

        update_hashes(db_conn, 2, "md5b", "sha256b", "2026-01-01T00:00:00Z")
        db_conn.commit()

        cursor = iter_unhashed_files(db_conn)
        rows = cursor.fetchall()

        assert len(rows) == 2
        assert rows[0] == (1, "a.jpg", 100)
        assert rows[1] == (3, "c.jpg", 300)

    def test_returns_empty_when_all_hashed(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        db_conn.commit()

        update_hashes(db_conn, 1, "md5a", "sha256a", "2026-01-01T00:00:00Z")
        db_conn.commit()

        cursor = iter_unhashed_files(db_conn)
        rows = cursor.fetchall()

        assert len(rows) == 0

    def test_ordered_by_id(self, db_conn):
        insert_file(db_conn, "c.jpg", "c.jpg", ".jpg", 300)
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 200)
        db_conn.commit()

        cursor = iter_unhashed_files(db_conn)
        ids = [row[0] for row in cursor.fetchall()]

        assert ids == [1, 2, 3]


class TestUpdateHashes:
    def test_updates_hash_columns(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        db_conn.commit()

        update_hashes(db_conn, 1, "md5hex", "sha256hex", "2026-02-16T12:00:00Z")
        db_conn.commit()

        cursor = db_conn.execute("SELECT md5_hash, sha256_hash, hashed_at FROM files WHERE id = 1")
        row = cursor.fetchone()

        assert row[0] == "md5hex"
        assert row[1] == "sha256hex"
        assert row[2] == "2026-02-16T12:00:00Z"


class TestIterAllFiles:
    def test_returns_all_files(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(db_conn, "b.jpg", "subdir/b.jpg", ".jpg", 200)
        db_conn.commit()

        cursor = iter_all_files(db_conn)
        rows = cursor.fetchall()

        assert len(rows) == 2
        assert rows[0] == (1, "a.jpg")
        assert rows[1] == (2, "subdir/b.jpg")

    def test_returns_empty_when_no_files(self, db_conn):
        cursor = iter_all_files(db_conn)
        rows = cursor.fetchall()

        assert len(rows) == 0

    def test_ordered_by_id(self, db_conn):
        insert_file(db_conn, "c.jpg", "c.jpg", ".jpg", 300)
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 200)
        db_conn.commit()

        cursor = iter_all_files(db_conn)
        ids = [row[0] for row in cursor.fetchall()]

        assert ids == [1, 2, 3]


class TestDeleteFiles:
    def test_deletes_specified_files(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 200)
        insert_file(db_conn, "c.jpg", "c.jpg", ".jpg", 300)
        db_conn.commit()

        deleted = delete_files(db_conn, [1, 3])
        db_conn.commit()

        assert deleted == 2
        assert count_total_files(db_conn) == 1

        cursor = db_conn.execute("SELECT id FROM files")
        remaining = [row[0] for row in cursor.fetchall()]
        assert remaining == [2]

    def test_returns_zero_for_empty_list(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        db_conn.commit()

        deleted = delete_files(db_conn, [])

        assert deleted == 0
        assert count_total_files(db_conn) == 1

    def test_deletes_single_file(self, db_conn):
        insert_file(db_conn, "a.jpg", "a.jpg", ".jpg", 100)
        insert_file(db_conn, "b.jpg", "b.jpg", ".jpg", 200)
        db_conn.commit()

        deleted = delete_files(db_conn, [2])
        db_conn.commit()

        assert deleted == 1
        assert count_total_files(db_conn) == 1
