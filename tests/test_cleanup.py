"""Tests for the cleanup module."""

from app.cleanup import (
    DeletionPlan,
    DuplicateFile,
    FileDeletion,
    FolderStats,
    _build_folder_detail_lines,
    _expand_selected_folders,
    build_duplicate_groups,
    build_folder_tree_entries,
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
    def test_moves_files_to_delete_folder(self, tmp_path):
        """Default behavior: files are moved to _DELETE/ preserving relative paths."""
        scan_dir = tmp_path / "files"
        (scan_dir / "backup").mkdir(parents=True)
        (scan_dir / "backup" / "a.raw").write_bytes(b"content_a")
        (scan_dir / "backup" / "b.raw").write_bytes(b"content_b")
        (scan_dir / "orig").mkdir(parents=True)
        (scan_dir / "orig" / "a.raw").write_bytes(b"content_a")
        (scan_dir / "orig" / "b.raw").write_bytes(b"content_b")

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

        result = execute_deletions(conn=conn, base_path=scan_dir, plan=plan, force=False)

        assert result.deleted_count == 2
        assert result.deleted_bytes == 18
        assert result.failed_count == 0
        # Originals gone from source
        assert not (scan_dir / "backup" / "a.raw").exists()
        assert not (scan_dir / "backup" / "b.raw").exists()
        # Files moved to _DELETE/
        assert (scan_dir / "_DELETE" / "backup" / "a.raw").exists()
        assert (scan_dir / "_DELETE" / "backup" / "b.raw").exists()
        assert (scan_dir / "_DELETE" / "backup" / "a.raw").read_bytes() == b"content_a"
        assert (scan_dir / "_DELETE" / "backup" / "b.raw").read_bytes() == b"content_b"

        # DB entries removed
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_move_preserves_directory_structure(self, tmp_path):
        """Nested paths like backup/sub/a.raw -> _DELETE/backup/sub/a.raw."""
        scan_dir = tmp_path / "files"
        (scan_dir / "backup" / "sub").mkdir(parents=True)
        (scan_dir / "backup" / "sub" / "a.raw").write_bytes(b"content_a")
        (scan_dir / "orig").mkdir(parents=True)
        (scan_dir / "orig" / "a.raw").write_bytes(b"content_a")

        conn = open_database(tmp_path / "test.db")
        file_id = _insert_hashed_file(conn, "a.raw", "backup/sub/a.raw", ".raw", 9, "md5a", "shaa")

        plan = DeletionPlan(
            deletions=[
                FileDeletion(file_id=file_id, rel_path="backup/sub/a.raw", file_size=9, surviving_copy="orig/a.raw"),
            ],
            protected_paths=[],
            total_bytes=9,
        )

        result = execute_deletions(conn=conn, base_path=scan_dir, plan=plan, force=False)

        assert result.deleted_count == 1
        assert not (scan_dir / "backup" / "sub" / "a.raw").exists()
        assert (scan_dir / "_DELETE" / "backup" / "sub" / "a.raw").exists()
        assert (scan_dir / "_DELETE" / "backup" / "sub" / "a.raw").read_bytes() == b"content_a"
        conn.close()

    def test_force_permanently_deletes(self, tmp_path):
        """force=True uses unlink, no _DELETE/ folder created."""
        scan_dir = tmp_path / "files"
        (scan_dir / "backup").mkdir(parents=True)
        (scan_dir / "backup" / "a.raw").write_bytes(b"content_a")
        (scan_dir / "backup" / "b.raw").write_bytes(b"content_b")
        (scan_dir / "orig").mkdir(parents=True)
        (scan_dir / "orig" / "a.raw").write_bytes(b"content_a")
        (scan_dir / "orig" / "b.raw").write_bytes(b"content_b")

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

        result = execute_deletions(conn=conn, base_path=scan_dir, plan=plan, force=True)

        assert result.deleted_count == 2
        assert result.deleted_bytes == 18
        assert result.failed_count == 0
        assert not (scan_dir / "backup" / "a.raw").exists()
        assert not (scan_dir / "backup" / "b.raw").exists()
        # No _DELETE/ folder should exist
        assert not (scan_dir / "_DELETE").exists()

        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_move_skips_when_dest_exists(self, tmp_path):
        """If dest already exists in _DELETE/, warn and count as failure."""
        scan_dir = tmp_path / "files"
        (scan_dir / "backup").mkdir(parents=True)
        (scan_dir / "backup" / "a.raw").write_bytes(b"new_content")
        (scan_dir / "orig").mkdir(parents=True)
        (scan_dir / "orig" / "a.raw").write_bytes(b"new_content")

        # Pre-create the destination in _DELETE/
        (scan_dir / "_DELETE" / "backup").mkdir(parents=True)
        (scan_dir / "_DELETE" / "backup" / "a.raw").write_bytes(b"old_content")

        conn = open_database(tmp_path / "test.db")
        file_id = _insert_hashed_file(conn, "a.raw", "backup/a.raw", ".raw", 11, "md5a", "shaa")

        plan = DeletionPlan(
            deletions=[
                FileDeletion(file_id=file_id, rel_path="backup/a.raw", file_size=11, surviving_copy="orig/a.raw"),
            ],
            protected_paths=[],
            total_bytes=11,
        )

        result = execute_deletions(conn=conn, base_path=scan_dir, plan=plan, force=False)

        assert result.deleted_count == 0
        assert result.failed_count == 1
        assert result.failed_paths == ["backup/a.raw"]
        # Source file still exists (not moved)
        assert (scan_dir / "backup" / "a.raw").exists()
        # Existing _DELETE/ file not overwritten
        assert (scan_dir / "_DELETE" / "backup" / "a.raw").read_bytes() == b"old_content"
        # DB entry still present
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_handles_already_missing_file(self, tmp_path):
        """File already gone from disk — DB entry cleaned up (default move mode)."""
        scan_dir = tmp_path / "files"
        (scan_dir / "orig").mkdir(parents=True)
        (scan_dir / "orig" / "gone.raw").write_bytes(b"content")

        conn = open_database(tmp_path / "test.db")
        file_id = _insert_hashed_file(conn, "gone.raw", "backup/gone.raw", ".raw", 100, "md5g", "shag")

        plan = DeletionPlan(
            deletions=[
                FileDeletion(file_id=file_id, rel_path="backup/gone.raw", file_size=100, surviving_copy="orig/gone.raw"),
            ],
            protected_paths=[],
            total_bytes=100,
        )

        result = execute_deletions(conn=conn, base_path=scan_dir, plan=plan, force=False)

        assert result.deleted_count == 1
        assert result.failed_count == 0

        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_handles_already_missing_file_force(self, tmp_path):
        """File already gone from disk — DB entry cleaned up (force mode)."""
        scan_dir = tmp_path / "files"
        (scan_dir / "orig").mkdir(parents=True)
        (scan_dir / "orig" / "gone.raw").write_bytes(b"content")

        conn = open_database(tmp_path / "test.db")
        file_id = _insert_hashed_file(conn, "gone.raw", "backup/gone.raw", ".raw", 100, "md5g", "shag")

        plan = DeletionPlan(
            deletions=[
                FileDeletion(file_id=file_id, rel_path="backup/gone.raw", file_size=100, surviving_copy="orig/gone.raw"),
            ],
            protected_paths=[],
            total_bytes=100,
        )

        result = execute_deletions(conn=conn, base_path=scan_dir, plan=plan, force=True)

        assert result.deleted_count == 1
        assert result.failed_count == 0

        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_empty_plan(self, tmp_path):
        conn = open_database(tmp_path / "test.db")

        plan = DeletionPlan(deletions=[], protected_paths=[], total_bytes=0)

        result = execute_deletions(conn=conn, base_path=tmp_path, plan=plan, force=False)

        assert result.deleted_count == 0
        assert result.deleted_bytes == 0
        assert result.failed_count == 0
        conn.close()

    def test_aborts_when_surviving_copy_missing(self, tmp_path):
        # Surviving copy does NOT exist on disk — deletion must be blocked
        scan_dir = tmp_path / "files"
        (scan_dir / "backup").mkdir(parents=True)
        (scan_dir / "backup" / "a.raw").write_bytes(b"content_a")
        # orig/a.raw intentionally NOT created

        conn = open_database(tmp_path / "test.db")
        file_id = _insert_hashed_file(conn, "a.raw", "backup/a.raw", ".raw", 9, "md5a", "shaa")

        plan = DeletionPlan(
            deletions=[
                FileDeletion(file_id=file_id, rel_path="backup/a.raw", file_size=9, surviving_copy="orig/a.raw"),
            ],
            protected_paths=[],
            total_bytes=9,
        )

        result = execute_deletions(conn=conn, base_path=scan_dir, plan=plan, force=False)

        # Nothing should be deleted
        assert result.deleted_count == 0
        assert result.failed_count == 1
        # File still on disk
        assert (scan_dir / "backup" / "a.raw").exists()
        # DB entry still present
        cursor = conn.execute("SELECT COUNT(*) FROM files")
        assert cursor.fetchone()[0] == 1
        conn.close()


def _make_folder_stats(folder: str, duplicate_count: int, reclaimable_bytes: int) -> FolderStats:
    """Helper to create a FolderStats with no file details (sufficient for tree rendering)."""
    return FolderStats(
        folder=folder,
        duplicate_count=duplicate_count,
        reclaimable_bytes=reclaimable_bytes,
        files=[],
    )


class TestBuildFolderTreeEntries:
    def test_empty_list(self):
        entries, index_to_folder, folder_to_index, expandable = build_folder_tree_entries([], set())
        assert entries == []
        assert index_to_folder == {}
        assert folder_to_index == {}
        assert expandable == set()

    def test_single_top_level_folder(self):
        stats = [_make_folder_stats("photos", 10, 1024**3)]
        entries, index_to_folder, folder_to_index, expandable = build_folder_tree_entries(stats, set())
        assert len(entries) == 1
        assert entries[0] == "└── photos/  (10 duplicates, 1.00 GB)"
        assert index_to_folder == {0: "photos"}
        assert folder_to_index == {"photos": 0}
        assert expandable == set()

    def test_two_top_level_folders_sorted_alphabetically(self):
        stats = [
            _make_folder_stats("zebra", 5, 500),
            _make_folder_stats("alpha", 3, 300),
        ]
        entries, index_to_folder, folder_to_index, expandable = build_folder_tree_entries(stats, set())
        assert entries[0] == "├── alpha/  (3 duplicates, 300 B)"
        assert entries[1] == "└── zebra/  (5 duplicates, 500 B)"
        assert index_to_folder == {0: "alpha", 1: "zebra"}
        assert folder_to_index == {"alpha": 0, "zebra": 1}

    def test_nested_folders_collapsed_by_default(self):
        stats = [
            _make_folder_stats("photos/2020/vacation", 10, 1024**3),
            _make_folder_stats("photos/2020/work", 5, 512 * 1024**2),
        ]
        entries, index_to_folder, folder_to_index, expandable = build_folder_tree_entries(stats, set())
        # Collapsed: only top-level "photos" shown with ▸ indicator
        assert len(entries) == 1
        assert entries[0] == "└── ▸ photos/  (15 duplicates, 1.50 GB)"
        assert index_to_folder == {0: "photos"}
        assert folder_to_index == {"photos": 0}
        assert "photos" in expandable

    def test_nested_folders_fully_expanded(self):
        stats = [
            _make_folder_stats("photos/2020/vacation", 10, 1024**3),
            _make_folder_stats("photos/2020/work", 5, 512 * 1024**2),
        ]
        expanded = {"photos", "photos/2020"}
        entries, index_to_folder, folder_to_index, expandable = build_folder_tree_entries(stats, expanded)
        # Fully expanded: all levels visible with ▾ indicators on parents
        assert entries[0] == "└── ▾ photos/  (15 duplicates, 1.50 GB)"
        assert entries[1] == "    └── ▾ 2020/  (15 duplicates, 1.50 GB)"
        assert entries[2] == "        ├── vacation/  (10 duplicates, 1.00 GB)"
        assert entries[3] == "        └── work/  (5 duplicates, 512.00 MB)"
        # All entries are in index_to_folder (including intermediates)
        assert index_to_folder[0] == "photos"
        assert index_to_folder[1] == "photos/2020"
        assert index_to_folder[2] == "photos/2020/vacation"
        assert index_to_folder[3] == "photos/2020/work"
        assert expandable == {"photos", "photos/2020"}

    def test_intermediate_folder_with_stats_collapsed(self):
        stats = [
            _make_folder_stats("photos", 20, 2 * 1024**3),
            _make_folder_stats("photos/raw", 10, 1024**3),
        ]
        entries, index_to_folder, _, expandable = build_folder_tree_entries(stats, set())
        # Collapsed: only photos shown with ▸
        assert len(entries) == 1
        assert entries[0] == "└── ▸ photos/  (30 duplicates, 3.00 GB)"
        assert index_to_folder == {0: "photos"}
        assert "photos" in expandable

    def test_intermediate_folder_with_stats_expanded(self):
        stats = [
            _make_folder_stats("photos", 20, 2 * 1024**3),
            _make_folder_stats("photos/raw", 10, 1024**3),
        ]
        entries, index_to_folder, _, _ = build_folder_tree_entries(stats, {"photos"})
        # Expanded: photos/ with ▾ and raw/ visible
        assert entries[0] == "└── ▾ photos/  (30 duplicates, 3.00 GB)"
        assert entries[1] == "    └── raw/  (10 duplicates, 1.00 GB)"
        assert index_to_folder == {0: "photos", 1: "photos/raw"}

    def test_root_folder_dot(self):
        stats = [
            _make_folder_stats(".", 5, 500),
            _make_folder_stats("sub", 3, 300),
        ]
        entries, index_to_folder, folder_to_index, _ = build_folder_tree_entries(stats, set())
        assert entries[0] == "./  (5 duplicates, 500 B)"
        assert entries[1] == "└── sub/  (3 duplicates, 300 B)"
        assert index_to_folder == {0: ".", 1: "sub"}
        assert folder_to_index == {".": 0, "sub": 1}

    def test_tree_connectors_multiple_siblings(self):
        stats = [
            _make_folder_stats("a", 1, 100),
            _make_folder_stats("b", 2, 200),
            _make_folder_stats("c", 3, 300),
        ]
        entries, _, _, _ = build_folder_tree_entries(stats, set())
        assert "├── a/" in entries[0]
        assert "├── b/" in entries[1]
        assert "└── c/" in entries[2]

    def test_no_files_in_tree_entries(self):
        stats = [
            FolderStats(
                folder="photos",
                duplicate_count=3,
                reclaimable_bytes=300,
                files=[
                    DuplicateFile(1, "photos/IMG_001.CR2", 100, "k1", "photos"),
                    DuplicateFile(2, "photos/IMG_002.CR2", 100, "k2", "photos"),
                    DuplicateFile(3, "photos/IMG_003.CR2", 100, "k3", "photos"),
                ],
            ),
        ]
        entries, index_to_folder, _, _ = build_folder_tree_entries(stats, set())
        assert len(entries) == 1
        assert entries[0] == "└── photos/  (3 duplicates, 300 B)"
        assert index_to_folder == {0: "photos"}

    def test_deep_nesting_collapsed(self):
        stats = [
            _make_folder_stats("a/b/c", 5, 500),
            _make_folder_stats("a/d", 3, 300),
            _make_folder_stats("x/y", 2, 200),
        ]
        entries, index_to_folder, _, expandable = build_folder_tree_entries(stats, set())
        # Collapsed: only top-level folders visible
        assert entries[0] == "├── ▸ a/  (8 duplicates, 800 B)"
        assert entries[1] == "└── ▸ x/  (2 duplicates, 200 B)"
        assert len(entries) == 2
        assert index_to_folder == {0: "a", 1: "x"}
        assert "a" in expandable
        assert "x" in expandable

    def test_deep_nesting_fully_expanded(self):
        stats = [
            _make_folder_stats("a/b/c", 5, 500),
            _make_folder_stats("a/d", 3, 300),
            _make_folder_stats("x/y", 2, 200),
        ]
        expanded = {"a", "a/b", "x"}
        entries, index_to_folder, _, _ = build_folder_tree_entries(stats, expanded)
        assert entries[0] == "├── ▾ a/  (8 duplicates, 800 B)"
        assert entries[1] == "│   ├── ▾ b/  (5 duplicates, 500 B)"
        assert entries[2] == "│   │   └── c/  (5 duplicates, 500 B)"
        assert entries[3] == "│   └── d/  (3 duplicates, 300 B)"
        assert entries[4] == "└── ▾ x/  (2 duplicates, 200 B)"
        assert entries[5] == "    └── y/  (2 duplicates, 200 B)"
        # All entries are in index_to_folder
        assert index_to_folder == {
            0: "a",
            1: "a/b",
            2: "a/b/c",
            3: "a/d",
            4: "x",
            5: "x/y",
        }

    def test_partial_expand(self):
        stats = [
            _make_folder_stats("a/b/c", 5, 500),
            _make_folder_stats("a/d", 3, 300),
        ]
        # Only expand "a", not "a/b"
        entries, index_to_folder, _, expandable = build_folder_tree_entries(stats, {"a"})
        assert entries[0] == "└── ▾ a/  (8 duplicates, 800 B)"
        assert entries[1] == "    ├── ▸ b/  (5 duplicates, 500 B)"
        assert entries[2] == "    └── d/  (3 duplicates, 300 B)"
        assert len(entries) == 3
        assert index_to_folder == {0: "a", 1: "a/b", 2: "a/d"}
        assert "a/b" in expandable

    def test_folder_to_index_reverse_mapping(self):
        stats = [
            _make_folder_stats("alpha", 3, 300),
            _make_folder_stats("beta", 5, 500),
        ]
        _, _, folder_to_index, _ = build_folder_tree_entries(stats, set())
        assert folder_to_index["alpha"] == 0
        assert folder_to_index["beta"] == 1

    def test_expandable_set_correctness(self):
        stats = [
            _make_folder_stats("a/b", 5, 500),
            _make_folder_stats("c", 3, 300),
        ]
        _, _, _, expandable = build_folder_tree_entries(stats, set())
        assert expandable == {"a"}  # "a" has child "b", "c" is a leaf

    def test_expandable_includes_nested_parents(self):
        stats = [
            _make_folder_stats("a/b/c", 5, 500),
        ]
        expanded = {"a"}
        _, _, _, expandable = build_folder_tree_entries(stats, expanded)
        # "a" has child "b", "a/b" has child "c"
        assert "a" in expandable
        assert "a/b" in expandable


class TestExpandSelectedFolders:
    def test_direct_folder_included(self):
        result = _expand_selected_folders(["photos"], {"photos", "backup"})
        assert result == ["photos"]

    def test_parent_expands_to_descendants(self):
        all_with_dupes = {"photos/2020/vacation", "photos/2020/work", "backup"}
        result = _expand_selected_folders(["photos"], all_with_dupes)
        assert result == ["photos/2020/vacation", "photos/2020/work"]

    def test_parent_with_own_duplicates_and_descendants(self):
        all_with_dupes = {"photos", "photos/raw", "backup"}
        result = _expand_selected_folders(["photos"], all_with_dupes)
        assert result == ["photos", "photos/raw"]

    def test_leaf_folder_no_expansion(self):
        all_with_dupes = {"photos/2020/vacation", "photos/2020/work"}
        result = _expand_selected_folders(["photos/2020/vacation"], all_with_dupes)
        assert result == ["photos/2020/vacation"]

    def test_intermediate_without_own_duplicates(self):
        all_with_dupes = {"a/b/c", "a/d"}
        result = _expand_selected_folders(["a"], all_with_dupes)
        assert result == ["a/b/c", "a/d"]

    def test_empty_selection(self):
        result = _expand_selected_folders([], {"photos"})
        assert result == []

    def test_no_matching_descendants(self):
        result = _expand_selected_folders(["nonexistent"], {"photos"})
        assert result == []

    def test_deduplication(self):
        all_with_dupes = {"a/b", "a/c"}
        # Selecting both "a" (parent) and "a/b" (child) should not duplicate
        result = _expand_selected_folders(["a", "a/b"], all_with_dupes)
        assert result == ["a/b", "a/c"]


class TestBuildFolderDetailLines:
    def test_folder_not_in_stats(self):
        lines = _build_folder_detail_lines("nonexistent", {}, {})
        assert lines == ["No duplicate files in nonexistent/"]

    def test_single_file_two_copies(self):
        dup1 = DuplicateFile(1, "backup/a.raw", 1000, "grp1", "backup")
        dup2 = DuplicateFile(2, "originals/a.raw", 1000, "grp1", "originals")
        stats_by_folder = {
            "backup": FolderStats("backup", 1, 1000, [dup1]),
        }
        duplicate_groups = {"grp1": [dup1, dup2]}

        lines = _build_folder_detail_lines("backup", stats_by_folder, duplicate_groups)

        assert lines[0] == "Duplicate files in backup/ (1 files):"
        assert "  a.raw  (1000 B) — 2 copies:" in lines
        assert "    backup/a.raw" in lines
        assert "    originals/a.raw" in lines

    def test_multiple_files_sorted_by_copy_count(self):
        # File with 3 copies
        dup_a1 = DuplicateFile(1, "folder/a.raw", 1000, "grpA", "folder")
        dup_a2 = DuplicateFile(2, "copy1/a.raw", 1000, "grpA", "copy1")
        dup_a3 = DuplicateFile(3, "copy2/a.raw", 1000, "grpA", "copy2")
        # File with 2 copies
        dup_b1 = DuplicateFile(4, "folder/b.raw", 2000, "grpB", "folder")
        dup_b2 = DuplicateFile(5, "copy1/b.raw", 2000, "grpB", "copy1")

        stats_by_folder = {
            "folder": FolderStats("folder", 2, 3000, [dup_a1, dup_b1]),
        }
        duplicate_groups = {
            "grpA": [dup_a1, dup_a2, dup_a3],
            "grpB": [dup_b1, dup_b2],
        }

        lines = _build_folder_detail_lines("folder", stats_by_folder, duplicate_groups)

        # a.raw (3 copies) should appear before b.raw (2 copies)
        a_idx = next(i for i, line in enumerate(lines) if "a.raw" in line and "copies" in line)
        b_idx = next(i for i, line in enumerate(lines) if "b.raw" in line and "copies" in line)
        assert a_idx < b_idx
        assert "3 copies" in lines[a_idx]
        assert "2 copies" in lines[b_idx]

    def test_same_copy_count_sorted_by_filename(self):
        dup_z = DuplicateFile(1, "folder/zebra.raw", 1000, "grpZ", "folder")
        dup_z2 = DuplicateFile(2, "other/zebra.raw", 1000, "grpZ", "other")
        dup_a = DuplicateFile(3, "folder/alpha.raw", 2000, "grpA", "folder")
        dup_a2 = DuplicateFile(4, "other/alpha.raw", 2000, "grpA", "other")

        stats_by_folder = {
            "folder": FolderStats("folder", 2, 3000, [dup_z, dup_a]),
        }
        duplicate_groups = {
            "grpZ": [dup_z, dup_z2],
            "grpA": [dup_a, dup_a2],
        }

        lines = _build_folder_detail_lines("folder", stats_by_folder, duplicate_groups)

        # Same copy count (2 each) → sorted alphabetically: alpha before zebra
        a_idx = next(i for i, line in enumerate(lines) if "alpha.raw" in line and "copies" in line)
        z_idx = next(i for i, line in enumerate(lines) if "zebra.raw" in line and "copies" in line)
        assert a_idx < z_idx

    def test_deduplicates_same_group(self):
        # Two files in same folder from same group (unusual but possible)
        dup1 = DuplicateFile(1, "folder/a.raw", 1000, "grp1", "folder")
        dup2 = DuplicateFile(2, "folder/a_copy.raw", 1000, "grp1", "folder")
        dup3 = DuplicateFile(3, "other/a.raw", 1000, "grp1", "other")

        stats_by_folder = {
            "folder": FolderStats("folder", 2, 2000, [dup1, dup2]),
        }
        duplicate_groups = {"grp1": [dup1, dup2, dup3]}

        lines = _build_folder_detail_lines("folder", stats_by_folder, duplicate_groups)

        # Should show as 1 file entry (deduplicated by group_key)
        assert lines[0] == "Duplicate files in folder/ (1 files):"
        assert "3 copies" in "\n".join(lines)

    def test_copy_paths_sorted(self):
        dup1 = DuplicateFile(1, "z_folder/a.raw", 1000, "grp1", "z_folder")
        dup2 = DuplicateFile(2, "a_folder/a.raw", 1000, "grp1", "a_folder")
        dup3 = DuplicateFile(3, "m_folder/a.raw", 1000, "grp1", "m_folder")

        stats_by_folder = {
            "z_folder": FolderStats("z_folder", 1, 1000, [dup1]),
        }
        duplicate_groups = {"grp1": [dup1, dup2, dup3]}

        lines = _build_folder_detail_lines("z_folder", stats_by_folder, duplicate_groups)

        # Copy paths should be sorted alphabetically
        path_lines = [entry for entry in lines if entry.startswith("    ")]
        assert path_lines[0] == "    a_folder/a.raw"
        assert path_lines[1] == "    m_folder/a.raw"
        assert path_lines[2] == "    z_folder/a.raw"
