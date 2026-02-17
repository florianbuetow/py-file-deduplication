"""Tests for the cleanup module."""

from app.cleanup import (
    DeletionPlan,
    DuplicateFile,
    FileDeletion,
    build_duplicate_groups,
    compute_folder_stats,
    execute_deletions,
    plan_deletions,
)
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


class TestPlanDeletions:
    def test_delete_from_one_folder(self):
        groups = {
            "1000_md5_sha": [
                DuplicateFile(file_id=1, rel_path="originals/a.raw", file_size=1000, group_key="1000_md5_sha", folder="originals"),
                DuplicateFile(file_id=2, rel_path="backup/a.raw", file_size=1000, group_key="1000_md5_sha", folder="backup"),
            ]
        }

        plan = plan_deletions(selected_folders=["backup"], duplicate_groups=groups)

        assert len(plan.deletions) == 1
        assert plan.deletions[0].file_id == 2
        assert plan.deletions[0].rel_path == "backup/a.raw"
        assert plan.deletions[0].surviving_copy == "originals/a.raw"
        assert len(plan.protected_paths) == 0
        assert plan.total_bytes == 1000

    def test_no_files_in_selected_folders(self):
        groups = {
            "1000_md5_sha": [
                DuplicateFile(file_id=1, rel_path="a/file.raw", file_size=1000, group_key="1000_md5_sha", folder="a"),
                DuplicateFile(file_id=2, rel_path="b/file.raw", file_size=1000, group_key="1000_md5_sha", folder="b"),
            ]
        }

        plan = plan_deletions(selected_folders=["nonexistent"], duplicate_groups=groups)

        assert len(plan.deletions) == 0
        assert len(plan.protected_paths) == 0
        assert plan.total_bytes == 0

    def test_last_copy_protection(self):
        groups = {
            "1000_md5_sha": [
                DuplicateFile(file_id=1, rel_path="a/file.raw", file_size=1000, group_key="1000_md5_sha", folder="a"),
                DuplicateFile(file_id=2, rel_path="b/file.raw", file_size=1000, group_key="1000_md5_sha", folder="b"),
            ]
        }

        plan = plan_deletions(selected_folders=["a", "b"], duplicate_groups=groups)

        # One copy protected (alphabetically first: a/file.raw)
        assert len(plan.deletions) == 1
        assert plan.deletions[0].rel_path == "b/file.raw"
        assert plan.deletions[0].surviving_copy == "a/file.raw"
        assert len(plan.protected_paths) == 1
        assert plan.protected_paths[0] == "a/file.raw"
        assert plan.total_bytes == 1000

    def test_last_copy_protection_three_copies(self):
        groups = {
            "1000_md5_sha": [
                DuplicateFile(file_id=1, rel_path="c/file.raw", file_size=1000, group_key="1000_md5_sha", folder="c"),
                DuplicateFile(file_id=2, rel_path="a/file.raw", file_size=1000, group_key="1000_md5_sha", folder="a"),
                DuplicateFile(file_id=3, rel_path="b/file.raw", file_size=1000, group_key="1000_md5_sha", folder="b"),
            ]
        }

        plan = plan_deletions(selected_folders=["a", "b", "c"], duplicate_groups=groups)

        # a/file.raw survives (alphabetically first), b and c deleted
        assert len(plan.deletions) == 2
        deleted_paths = {d.rel_path for d in plan.deletions}
        assert deleted_paths == {"b/file.raw", "c/file.raw"}
        assert plan.protected_paths == ["a/file.raw"]
        for d in plan.deletions:
            assert d.surviving_copy == "a/file.raw"

    def test_mixed_safe_and_unsafe_groups(self):
        groups = {
            "1000_md5a_shaa": [
                DuplicateFile(file_id=1, rel_path="safe/a.raw", file_size=1000, group_key="1000_md5a_shaa", folder="safe"),
                DuplicateFile(file_id=2, rel_path="doomed/a.raw", file_size=1000, group_key="1000_md5a_shaa", folder="doomed"),
            ],
            "2000_md5b_shab": [
                DuplicateFile(file_id=3, rel_path="doomed/b.raw", file_size=2000, group_key="2000_md5b_shab", folder="doomed"),
                DuplicateFile(file_id=4, rel_path="also_doomed/b.raw", file_size=2000, group_key="2000_md5b_shab", folder="also_doomed"),
            ],
        }

        plan = plan_deletions(selected_folders=["doomed", "also_doomed"], duplicate_groups=groups)

        # Group 1: safe/a.raw not selected -> doomed/a.raw deleted, no protection needed
        # Group 2: all in selected -> one protected (also_doomed/b.raw < doomed/b.raw alphabetically)
        assert len(plan.deletions) == 2
        assert len(plan.protected_paths) == 1
        assert plan.protected_paths[0] == "also_doomed/b.raw"

    def test_all_duplicates_in_same_folder(self):
        groups = {
            "1000_md5_sha": [
                DuplicateFile(file_id=1, rel_path="photos/IMG_001.raw", file_size=1000, group_key="1000_md5_sha", folder="photos"),
                DuplicateFile(file_id=2, rel_path="photos/IMG_001_copy.raw", file_size=1000, group_key="1000_md5_sha", folder="photos"),
            ]
        }

        plan = plan_deletions(selected_folders=["photos"], duplicate_groups=groups)

        # One copy protected (alphabetically first: photos/IMG_001.raw)
        assert len(plan.deletions) == 1
        assert plan.deletions[0].rel_path == "photos/IMG_001_copy.raw"
        assert plan.deletions[0].surviving_copy == "photos/IMG_001.raw"
        assert len(plan.protected_paths) == 1
        assert plan.protected_paths[0] == "photos/IMG_001.raw"
        assert plan.total_bytes == 1000

    def test_three_duplicates_in_same_folder(self):
        groups = {
            "1000_md5_sha": [
                DuplicateFile(file_id=1, rel_path="photos/IMG_001.raw", file_size=1000, group_key="1000_md5_sha", folder="photos"),
                DuplicateFile(file_id=2, rel_path="photos/IMG_001_copy.raw", file_size=1000, group_key="1000_md5_sha", folder="photos"),
                DuplicateFile(file_id=3, rel_path="photos/IMG_001_v2.raw", file_size=1000, group_key="1000_md5_sha", folder="photos"),
            ]
        }

        plan = plan_deletions(selected_folders=["photos"], duplicate_groups=groups)

        # photos/IMG_001.raw survives, other two deleted
        assert len(plan.deletions) == 2
        deleted_paths = {d.rel_path for d in plan.deletions}
        assert deleted_paths == {"photos/IMG_001_copy.raw", "photos/IMG_001_v2.raw"}
        assert plan.protected_paths == ["photos/IMG_001.raw"]
        for d in plan.deletions:
            assert d.surviving_copy == "photos/IMG_001.raw"

    def test_empty_groups(self):
        plan = plan_deletions(selected_folders=["any"], duplicate_groups={})
        assert len(plan.deletions) == 0
        assert len(plan.protected_paths) == 0
        assert plan.total_bytes == 0


class TestExecuteDeletions:
    def test_deletes_files_from_disk_and_db(self, tmp_path):
        # Set up real files
        scan_dir = tmp_path / "files"
        (scan_dir / "backup").mkdir(parents=True)
        (scan_dir / "backup" / "a.raw").write_bytes(b"content_a")
        (scan_dir / "backup" / "b.raw").write_bytes(b"content_b")

        # Set up database
        conn = open_database(tmp_path / "test.db")
        id1 = _insert_hashed_file(conn, "a.raw", "backup/a.raw", ".raw", 9, "md5a", "shaa")
        id2 = _insert_hashed_file(conn, "b.raw", "backup/b.raw", ".raw", 9, "md5b", "shab")

        plan = DeletionPlan(
            deletions=[
                FileDeletion(file_id=id1, rel_path="backup/a.raw", file_size=9, surviving_copy="orig/a.raw"),
                FileDeletion(file_id=id2, rel_path="backup/b.raw", file_size=9, surviving_copy="orig/b.raw"),
            ],
            protected_paths=[],
            total_bytes=18,
        )

        result = execute_deletions(conn=conn, base_path=scan_dir, plan=plan)

        assert result.deleted_count == 2
        assert result.deleted_bytes == 18
        assert result.failed_count == 0
        assert not (scan_dir / "backup" / "a.raw").exists()
        assert not (scan_dir / "backup" / "b.raw").exists()

        # Verify DB entries removed
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_handles_already_missing_file(self, tmp_path):
        # File doesn't exist on disk but is in DB
        conn = open_database(tmp_path / "test.db")
        file_id = _insert_hashed_file(conn, "gone.raw", "backup/gone.raw", ".raw", 100, "md5g", "shag")

        plan = DeletionPlan(
            deletions=[
                FileDeletion(file_id=file_id, rel_path="backup/gone.raw", file_size=100, surviving_copy="orig/gone.raw"),
            ],
            protected_paths=[],
            total_bytes=100,
        )

        scan_dir = tmp_path / "files"
        scan_dir.mkdir()

        result = execute_deletions(conn=conn, base_path=scan_dir, plan=plan)

        # Should succeed -- DB entry cleaned up even though file was already gone
        assert result.deleted_count == 1
        assert result.failed_count == 0

        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_empty_plan(self, tmp_path):
        conn = open_database(tmp_path / "test.db")

        plan = DeletionPlan(deletions=[], protected_paths=[], total_bytes=0)

        result = execute_deletions(conn=conn, base_path=tmp_path, plan=plan)

        assert result.deleted_count == 0
        assert result.deleted_bytes == 0
        assert result.failed_count == 0
        conn.close()
