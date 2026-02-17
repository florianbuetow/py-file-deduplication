"""Tests for the duplicates module."""

from app.database import insert_file, open_database, update_hashes
from app.duplicates import _format_size, find_duplicates


def _insert_hashed_file(conn, filename, rel_path, extension, file_size, md5_hash, sha256_hash):
    """Helper to insert a file and immediately set its hashes."""
    insert_file(conn, filename, rel_path, extension, file_size)
    conn.commit()
    cursor = conn.execute("SELECT id FROM files WHERE rel_path = ?", (rel_path,))
    file_id = cursor.fetchone()[0]
    update_hashes(conn, file_id, md5_hash, sha256_hash, "2025-01-01T00:00:00+00:00")
    conn.commit()


class TestFormatSize:
    def test_bytes(self):
        assert _format_size(0) == "0 B"
        assert _format_size(500) == "500 B"
        assert _format_size(1023) == "1023 B"

    def test_kilobytes(self):
        assert _format_size(1024) == "1.00 KB"
        assert _format_size(1536) == "1.50 KB"
        assert _format_size(1048575) == "1024.00 KB"

    def test_megabytes(self):
        assert _format_size(1048576) == "1.00 MB"
        assert _format_size(1572864) == "1.50 MB"
        assert _format_size(1073741823) == "1024.00 MB"

    def test_gigabytes(self):
        assert _format_size(1073741824) == "1.00 GB"
        assert _format_size(1610612736) == "1.50 GB"
        assert _format_size(10737418240) == "10.00 GB"


class TestFindDuplicates:
    def test_no_hashed_files(self, tmp_path, capsys):
        db_path = tmp_path / "test.db"
        conn = open_database(db_path)

        find_duplicates(conn=conn)

        output = capsys.readouterr().out
        assert "Computing duplicates from database..." in output
        assert "Total hashed files analyzed: 0" in output
        assert "No duplicates found." in output

        conn.close()

    def test_all_unique_files(self, tmp_path, capsys):
        db_path = tmp_path / "test.db"
        conn = open_database(db_path)

        _insert_hashed_file(conn, "a.jpg", "a.jpg", ".jpg", 1000, "md5_aaa", "sha_aaa")
        _insert_hashed_file(conn, "b.jpg", "b.jpg", ".jpg", 2000, "md5_bbb", "sha_bbb")
        _insert_hashed_file(conn, "c.jpg", "c.jpg", ".jpg", 3000, "md5_ccc", "sha_ccc")

        find_duplicates(conn=conn)

        output = capsys.readouterr().out
        assert "Total hashed files analyzed: 3" in output
        assert "No duplicates found." in output

        conn.close()

    def test_one_pair_of_duplicates(self, tmp_path, capsys):
        db_path = tmp_path / "test.db"
        conn = open_database(db_path)

        _insert_hashed_file(conn, "a.jpg", "a.jpg", ".jpg", 1000, "md5_same", "sha_same")
        _insert_hashed_file(conn, "b.jpg", "dir/b.jpg", ".jpg", 1000, "md5_same", "sha_same")
        _insert_hashed_file(conn, "c.jpg", "c.jpg", ".jpg", 2000, "md5_unique", "sha_unique")

        find_duplicates(conn=conn)

        output = capsys.readouterr().out
        assert "Total hashed files analyzed: 3" in output
        assert "Duplicate files found: 2" in output
        assert "Duplicate groups: 1" in output
        assert "1 group with 2 copies each" in output
        assert "Reclaimable space: 1000 B" in output

        conn.close()

    def test_multiple_duplicate_groups(self, tmp_path, capsys):
        db_path = tmp_path / "test.db"
        conn = open_database(db_path)

        # Group 1: 2 files with same hash
        _insert_hashed_file(conn, "a1.jpg", "a1.jpg", ".jpg", 1000, "md5_g1", "sha_g1")
        _insert_hashed_file(conn, "a2.jpg", "a2.jpg", ".jpg", 1000, "md5_g1", "sha_g1")

        # Group 2: 3 files with same hash
        _insert_hashed_file(conn, "b1.jpg", "b1.jpg", ".jpg", 2000, "md5_g2", "sha_g2")
        _insert_hashed_file(conn, "b2.jpg", "b2.jpg", ".jpg", 2000, "md5_g2", "sha_g2")
        _insert_hashed_file(conn, "b3.jpg", "b3.jpg", ".jpg", 2000, "md5_g2", "sha_g2")

        # Unique file
        _insert_hashed_file(conn, "u.jpg", "u.jpg", ".jpg", 5000, "md5_uniq", "sha_uniq")

        find_duplicates(conn=conn)

        output = capsys.readouterr().out
        assert "Total hashed files analyzed: 6" in output
        assert "Duplicate files found: 5" in output
        assert "Duplicate groups: 2" in output
        assert "1 group with 2 copies each" in output
        assert "1 group with 3 copies each" in output
        # Reclaimable: (2-1)*1000 + (3-1)*2000 = 1000 + 4000 = 5000 B = 4.88 KB
        assert "Reclaimable space: 4.88 KB" in output

        conn.close()

    def test_reclaimable_space_large(self, tmp_path, capsys):
        db_path = tmp_path / "test.db"
        conn = open_database(db_path)

        file_size = 50 * 1024 * 1024  # 50 MB each
        _insert_hashed_file(conn, "a.jpg", "a.jpg", ".jpg", file_size, "md5_dup", "sha_dup")
        _insert_hashed_file(conn, "b.jpg", "b.jpg", ".jpg", file_size, "md5_dup", "sha_dup")
        _insert_hashed_file(conn, "c.jpg", "c.jpg", ".jpg", file_size, "md5_dup", "sha_dup")

        find_duplicates(conn=conn)

        output = capsys.readouterr().out
        assert "Duplicate files found: 3" in output
        # Reclaimable: (3-1) * 50 MB = 100 MB
        assert "Reclaimable space: 100.00 MB" in output

        conn.close()

    def test_same_hash_different_size_not_duplicates(self, tmp_path, capsys):
        db_path = tmp_path / "test.db"
        conn = open_database(db_path)

        # Same hashes but different file sizes should NOT be grouped
        _insert_hashed_file(conn, "a.jpg", "a.jpg", ".jpg", 1000, "md5_same", "sha_same")
        _insert_hashed_file(conn, "b.jpg", "b.jpg", ".jpg", 2000, "md5_same", "sha_same")

        find_duplicates(conn=conn)

        output = capsys.readouterr().out
        assert "No duplicates found." in output

        conn.close()

    def test_unhashed_files_excluded(self, tmp_path, capsys):
        db_path = tmp_path / "test.db"
        conn = open_database(db_path)

        # Insert an unhashed file (no hashes set)
        insert_file(conn, "unhashed.jpg", "unhashed.jpg", ".jpg", 1000)
        conn.commit()

        # Insert two hashed duplicates
        _insert_hashed_file(conn, "a.jpg", "a.jpg", ".jpg", 2000, "md5_dup", "sha_dup")
        _insert_hashed_file(conn, "b.jpg", "b.jpg", ".jpg", 2000, "md5_dup", "sha_dup")

        find_duplicates(conn=conn)

        output = capsys.readouterr().out
        # Should only count the 2 hashed files, not the unhashed one
        assert "Total hashed files analyzed: 2" in output
        assert "Duplicate files found: 2" in output

        conn.close()

    def test_distribution_multiple_groups_same_count(self, tmp_path, capsys):
        db_path = tmp_path / "test.db"
        conn = open_database(db_path)

        # 3 groups, each with exactly 2 duplicates
        _insert_hashed_file(conn, "a1.jpg", "a1.jpg", ".jpg", 100, "md5_a", "sha_a")
        _insert_hashed_file(conn, "a2.jpg", "a2.jpg", ".jpg", 100, "md5_a", "sha_a")

        _insert_hashed_file(conn, "b1.jpg", "b1.jpg", ".jpg", 200, "md5_b", "sha_b")
        _insert_hashed_file(conn, "b2.jpg", "b2.jpg", ".jpg", 200, "md5_b", "sha_b")

        _insert_hashed_file(conn, "c1.jpg", "c1.jpg", ".jpg", 300, "md5_c", "sha_c")
        _insert_hashed_file(conn, "c2.jpg", "c2.jpg", ".jpg", 300, "md5_c", "sha_c")

        find_duplicates(conn=conn)

        output = capsys.readouterr().out
        assert "Duplicate files found: 6" in output
        assert "Duplicate groups: 3" in output
        assert "3 groups with 2 copies each" in output
        # Reclaimable: 100 + 200 + 300 = 600 B
        assert "Reclaimable space: 600 B" in output

        conn.close()


class TestFindDuplicatesCli:
    def test_end_to_end(self, tmp_path, capsys):
        """Test run_duplicates via CLI entry point."""
        import yaml

        from app.cli import run_duplicates

        project_root = tmp_path / "project"
        project_root.mkdir()
        scan_dir = tmp_path / "files"
        scan_dir.mkdir()

        config_path = project_root / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "paths": [str(scan_dir)],
                    "extensions": [".jpg"],
                    "case_sensitive": False,
                    "recursive": True,
                    "skip_dirs": [".git"],
                    "database": str(project_root / "data" / "files.db"),
                }
            )
        )

        # Create the database and insert hashed duplicates directly
        db_path = project_root / "data" / "files.db"
        conn = open_database(db_path)

        _insert_hashed_file(conn, "a.jpg", "a.jpg", ".jpg", 1000, "md5_x", "sha_x")
        _insert_hashed_file(conn, "b.jpg", "b.jpg", ".jpg", 1000, "md5_x", "sha_x")

        conn.close()

        run_duplicates(project_root=project_root)

        output = capsys.readouterr().out
        assert "Database:" in output
        assert "Duplicate files found: 2" in output
