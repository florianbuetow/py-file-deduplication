"""Tests for the cleanup module."""

from app.cleanup import (
    DeletionPlan,
    DuplicateFile,
    FileDeletion,
    FolderStats,
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
    def test_deletes_files_from_disk_and_db(self, tmp_path):
        # Set up real files (including surviving copies)
        scan_dir = tmp_path / "files"
        (scan_dir / "backup").mkdir(parents=True)
        (scan_dir / "backup" / "a.raw").write_bytes(b"content_a")
        (scan_dir / "backup" / "b.raw").write_bytes(b"content_b")
        (scan_dir / "orig").mkdir(parents=True)
        (scan_dir / "orig" / "a.raw").write_bytes(b"content_a")
        (scan_dir / "orig" / "b.raw").write_bytes(b"content_b")

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
        # File to delete doesn't exist on disk but is in DB; surviving copy exists
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

        result = execute_deletions(conn=conn, base_path=scan_dir, plan=plan)

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
