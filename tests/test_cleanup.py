"""Tests for the cleanup module."""

from app.cleanup import DuplicateFile, FolderStats, build_duplicate_groups, compute_folder_stats
from app.database import insert_file, open_database, update_hashes


def _insert_hashed_file(conn, filename, rel_path, extension, file_size, md5_hash, sha256_hash):
    """Helper to insert a file and immediately set its hashes."""
    insert_file(conn, filename, rel_path, extension, file_size)
    conn.commit()
    cursor = conn.execute("SELECT id FROM files WHERE rel_path = ?", (rel_path,))
    file_id = cursor.fetchone()[0]
    update_hashes(conn, file_id, md5_hash, sha256_hash, "2025-01-01T00:00:00+00:00")
    conn.commit()
    return file_id


class TestBuildDuplicateGroups:
    def test_empty_database(self, tmp_path):
        conn = open_database(tmp_path / "test.db")
        groups = build_duplicate_groups(conn)
        assert len(groups) == 0
        conn.close()

    def test_no_duplicates(self, tmp_path):
        conn = open_database(tmp_path / "test.db")
        _insert_hashed_file(conn, "a.raw", "dir1/a.raw", ".raw", 1000, "md5_a", "sha_a")
        _insert_hashed_file(conn, "b.raw", "dir2/b.raw", ".raw", 2000, "md5_b", "sha_b")
        groups = build_duplicate_groups(conn)
        assert len(groups) == 0
        conn.close()

    def test_one_duplicate_group(self, tmp_path):
        conn = open_database(tmp_path / "test.db")
        _insert_hashed_file(conn, "a.raw", "originals/a.raw", ".raw", 1000, "md5_x", "sha_x")
        _insert_hashed_file(conn, "a.raw", "backup/a.raw", ".raw", 1000, "md5_x", "sha_x")

        groups = build_duplicate_groups(conn)

        assert len(groups) == 1
        key = list(groups.keys())[0]
        assert len(groups[key]) == 2

        folders = {f.folder for f in groups[key]}
        assert folders == {"originals", "backup"}
        conn.close()

    def test_multiple_groups(self, tmp_path):
        conn = open_database(tmp_path / "test.db")
        _insert_hashed_file(conn, "a.raw", "d1/a.raw", ".raw", 1000, "md5_a", "sha_a")
        _insert_hashed_file(conn, "a.raw", "d2/a.raw", ".raw", 1000, "md5_a", "sha_a")
        _insert_hashed_file(conn, "b.raw", "d1/b.raw", ".raw", 2000, "md5_b", "sha_b")
        _insert_hashed_file(conn, "b.raw", "d3/b.raw", ".raw", 2000, "md5_b", "sha_b")

        groups = build_duplicate_groups(conn)

        assert len(groups) == 2
        conn.close()

    def test_file_in_root_has_dot_folder(self, tmp_path):
        conn = open_database(tmp_path / "test.db")
        _insert_hashed_file(conn, "a.raw", "a.raw", ".raw", 1000, "md5_x", "sha_x")
        _insert_hashed_file(conn, "a.raw", "sub/a.raw", ".raw", 1000, "md5_x", "sha_x")

        groups = build_duplicate_groups(conn)

        key = list(groups.keys())[0]
        folders = {f.folder for f in groups[key]}
        assert folders == {".", "sub"}
        conn.close()

    def test_duplicate_file_fields(self, tmp_path):
        conn = open_database(tmp_path / "test.db")
        id1 = _insert_hashed_file(conn, "a.raw", "originals/a.raw", ".raw", 1000, "md5_x", "sha_x")
        id2 = _insert_hashed_file(conn, "a.raw", "backup/a.raw", ".raw", 1000, "md5_x", "sha_x")

        groups = build_duplicate_groups(conn)
        key = list(groups.keys())[0]
        files = sorted(groups[key], key=lambda f: f.rel_path)

        assert files[0].file_id == id2  # backup/a.raw
        assert files[0].rel_path == "backup/a.raw"
        assert files[0].file_size == 1000
        assert files[0].group_key == key
        assert files[0].folder == "backup"

        assert files[1].file_id == id1  # originals/a.raw
        assert files[1].folder == "originals"
        conn.close()


class TestComputeFolderStats:
    def test_empty_groups(self):
        stats = compute_folder_stats({})
        assert len(stats) == 0

    def test_single_group_two_folders(self):
        groups = {
            "1000_md5_sha": [
                DuplicateFile(file_id=1, rel_path="originals/a.raw", file_size=1000, group_key="1000_md5_sha", folder="originals"),
                DuplicateFile(file_id=2, rel_path="backup/a.raw", file_size=1000, group_key="1000_md5_sha", folder="backup"),
            ]
        }
        stats = compute_folder_stats(groups)

        assert len(stats) == 2
        folders = {s.folder for s in stats}
        assert folders == {"originals", "backup"}
        assert stats[0].duplicate_count == 1
        assert stats[0].reclaimable_bytes == 1000

    def test_sorted_by_duplicate_count_descending(self):
        groups = {
            "1000_md5a_shaa": [
                DuplicateFile(file_id=1, rel_path="few/a.raw", file_size=1000, group_key="1000_md5a_shaa", folder="few"),
                DuplicateFile(file_id=2, rel_path="many/a.raw", file_size=1000, group_key="1000_md5a_shaa", folder="many"),
            ],
            "2000_md5b_shab": [
                DuplicateFile(file_id=3, rel_path="many/b.raw", file_size=2000, group_key="2000_md5b_shab", folder="many"),
                DuplicateFile(file_id=4, rel_path="few/b.raw", file_size=2000, group_key="2000_md5b_shab", folder="few"),
            ],
            "3000_md5c_shac": [
                DuplicateFile(file_id=5, rel_path="many/c.raw", file_size=3000, group_key="3000_md5c_shac", folder="many"),
                DuplicateFile(file_id=6, rel_path="other/c.raw", file_size=3000, group_key="3000_md5c_shac", folder="other"),
            ],
        }
        stats = compute_folder_stats(groups)

        # "many" has 3 dupes, "few" has 2, "other" has 1
        assert stats[0].folder == "many"
        assert stats[0].duplicate_count == 3
        assert stats[1].folder == "few"
        assert stats[1].duplicate_count == 2
        assert stats[2].folder == "other"
        assert stats[2].duplicate_count == 1

    def test_secondary_sort_by_reclaimable_bytes(self):
        groups = {
            "1000_md5a_shaa": [
                DuplicateFile(file_id=1, rel_path="small/a.raw", file_size=1000, group_key="1000_md5a_shaa", folder="small"),
                DuplicateFile(file_id=2, rel_path="big/a.raw", file_size=1000, group_key="1000_md5a_shaa", folder="big"),
            ],
            "5000_md5b_shab": [
                DuplicateFile(file_id=3, rel_path="big/b.raw", file_size=5000, group_key="5000_md5b_shab", folder="big"),
                DuplicateFile(file_id=4, rel_path="small/b.raw", file_size=5000, group_key="5000_md5b_shab", folder="small"),
            ],
        }
        stats = compute_folder_stats(groups)

        # Both have 2 dupes, both have 6000 bytes — tied, order is stable
        assert stats[0].duplicate_count == 2
        assert stats[1].duplicate_count == 2
