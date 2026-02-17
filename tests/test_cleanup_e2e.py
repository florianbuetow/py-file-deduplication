"""End-to-end tests for the cleanup feature with real files on disk."""

from pathlib import Path

import yaml

from app.cleanup import (
    build_duplicate_groups,
    compute_folder_stats,
    execute_deletions,
    plan_deletions,
)
from app.cli import run_hash, run_scan
from app.database import count_total_files, open_database


def _create_test_project(tmp_path):
    """Create a test project with duplicate files on disk.

    Directory structure:
        files/
            originals/
                photo1.raw  (content: AAA...)
                photo2.raw  (content: BBB...)
                photo3.raw  (content: CCC...)
            backup1/
                photo1.raw  (dup of originals/photo1)
                photo2.raw  (dup of originals/photo2)
            backup2/
                photo1.raw  (dup of originals/photo1)
                photo2.raw  (dup of originals/photo2)
                photo3.raw  (dup of originals/photo3)
            unique_folder/
                solo.raw    (no duplicates)

    Returns:
        Tuple of (project_root, scan_dir, db_path).
    """
    scan_dir = tmp_path / "files"
    originals = scan_dir / "originals"
    backup1 = scan_dir / "backup1"
    backup2 = scan_dir / "backup2"
    unique_folder = scan_dir / "unique_folder"

    for d in [originals, backup1, backup2, unique_folder]:
        d.mkdir(parents=True)

    content_a = b"A" * 1024
    content_b = b"B" * 2048
    content_c = b"C" * 4096
    content_solo = b"S" * 512

    (originals / "photo1.raw").write_bytes(content_a)
    (originals / "photo2.raw").write_bytes(content_b)
    (originals / "photo3.raw").write_bytes(content_c)

    (backup1 / "photo1.raw").write_bytes(content_a)
    (backup1 / "photo2.raw").write_bytes(content_b)

    (backup2 / "photo1.raw").write_bytes(content_a)
    (backup2 / "photo2.raw").write_bytes(content_b)
    (backup2 / "photo3.raw").write_bytes(content_c)

    (unique_folder / "solo.raw").write_bytes(content_solo)

    project_root = tmp_path / "project"
    project_root.mkdir()

    db_path = project_root / "data" / "files.db"
    config = {
        "paths": [str(scan_dir)],
        "extensions": [".raw"],
        "case_sensitive": False,
        "recursive": True,
        "skip_dirs": [],
        "database": str(db_path),
    }
    (project_root / "config.yaml").write_text(yaml.dump(config))

    return project_root, scan_dir, db_path


class TestCleanupE2E:
    def test_full_pipeline_delete_one_folder(self, tmp_path):
        """Scan, hash, analyze, delete backup1, verify."""
        project_root, scan_dir, db_path = _create_test_project(tmp_path)

        # Run scan and hash via CLI functions
        run_scan(project_root=project_root)
        run_hash(project_root=project_root)

        # Open DB and analyze
        conn = open_database(db_path)
        assert count_total_files(conn) == 9

        groups = build_duplicate_groups(conn)
        assert len(groups) == 3  # photo1, photo2, photo3

        folder_stats = compute_folder_stats(groups)
        folder_names = [s.folder for s in folder_stats]
        # All three folders with dupes should appear
        assert "originals" in folder_names
        assert "backup1" in folder_names
        assert "backup2" in folder_names
        # unique_folder should NOT appear (no dupes)
        assert "unique_folder" not in folder_names

        # Plan deletion of backup1
        plan = plan_deletions(selected_folders=["backup1"], duplicate_groups=groups)
        assert len(plan.deletions) == 2  # photo1 and photo2 in backup1
        assert len(plan.protected_paths) == 0  # copies survive in originals + backup2

        # Execute
        base_path = Path(scan_dir).resolve()
        result = execute_deletions(conn=conn, base_path=base_path, plan=plan)

        assert result.deleted_count == 2
        assert result.failed_count == 0

        # Verify disk state
        assert not (scan_dir / "backup1" / "photo1.raw").exists()
        assert not (scan_dir / "backup1" / "photo2.raw").exists()

        assert (scan_dir / "originals" / "photo1.raw").exists()
        assert (scan_dir / "originals" / "photo2.raw").exists()
        assert (scan_dir / "originals" / "photo3.raw").exists()

        assert (scan_dir / "backup2" / "photo1.raw").exists()
        assert (scan_dir / "backup2" / "photo2.raw").exists()
        assert (scan_dir / "backup2" / "photo3.raw").exists()

        assert (scan_dir / "unique_folder" / "solo.raw").exists()

        # Verify DB state
        assert count_total_files(conn) == 7  # 9 - 2 deleted

        conn.close()

    def test_delete_multiple_folders(self, tmp_path):
        """Delete both backup1 and backup2, originals survive."""
        project_root, scan_dir, db_path = _create_test_project(tmp_path)

        run_scan(project_root=project_root)
        run_hash(project_root=project_root)

        conn = open_database(db_path)
        groups = build_duplicate_groups(conn)

        plan = plan_deletions(selected_folders=["backup1", "backup2"], duplicate_groups=groups)
        # backup1 has 2, backup2 has 3 -> 5 deletions total
        assert len(plan.deletions) == 5
        assert len(plan.protected_paths) == 0  # originals always safe

        result = execute_deletions(conn=conn, base_path=scan_dir.resolve(), plan=plan)
        assert result.deleted_count == 5

        # All originals and unique_folder survive
        assert (scan_dir / "originals" / "photo1.raw").exists()
        assert (scan_dir / "originals" / "photo2.raw").exists()
        assert (scan_dir / "originals" / "photo3.raw").exists()
        assert (scan_dir / "unique_folder" / "solo.raw").exists()

        assert count_total_files(conn) == 4  # 9 - 5
        conn.close()

    def test_last_copy_protection_e2e(self, tmp_path):
        """Select ALL folders -- last-copy protection keeps one copy of each."""
        project_root, scan_dir, db_path = _create_test_project(tmp_path)

        run_scan(project_root=project_root)
        run_hash(project_root=project_root)

        conn = open_database(db_path)
        groups = build_duplicate_groups(conn)

        # Select all folders that have duplicates
        folder_stats = compute_folder_stats(groups)
        all_folders = [s.folder for s in folder_stats]

        plan = plan_deletions(selected_folders=all_folders, duplicate_groups=groups)

        # 3 groups, each should protect 1 -> 3 protected
        assert len(plan.protected_paths) == 3

        # Total files to delete: group1 has 3 copies (del 2), group2 has 3 (del 2), group3 has 2 (del 1) = 5
        assert len(plan.deletions) == 5

        result = execute_deletions(conn=conn, base_path=scan_dir.resolve(), plan=plan)
        assert result.deleted_count == 5

        # Verify exactly one copy of each content survives
        photo1_survivors = []
        photo2_survivors = []
        photo3_survivors = []
        for folder in ["originals", "backup1", "backup2"]:
            if (scan_dir / folder / "photo1.raw").exists():
                photo1_survivors.append(folder)
            if (scan_dir / folder / "photo2.raw").exists():
                photo2_survivors.append(folder)
            if (scan_dir / folder / "photo3.raw").exists():
                photo3_survivors.append(folder)

        assert len(photo1_survivors) == 1
        assert len(photo2_survivors) == 1
        assert len(photo3_survivors) == 1

        # unique_folder untouched
        assert (scan_dir / "unique_folder" / "solo.raw").exists()

        # DB: 9 original - 5 deleted = 4 (3 survivors + solo)
        assert count_total_files(conn) == 4
        conn.close()

    def test_all_duplicates_in_same_folder(self, tmp_path):
        """Duplicates with different names in the same folder — last-copy protection must keep one."""
        scan_dir = tmp_path / "files"
        photos = scan_dir / "photos"
        photos.mkdir(parents=True)

        content = b"X" * 2048
        (photos / "IMG_001.raw").write_bytes(content)
        (photos / "IMG_001_copy.raw").write_bytes(content)
        (photos / "IMG_001_v2.raw").write_bytes(content)

        project_root = tmp_path / "project"
        project_root.mkdir()
        db_path = project_root / "data" / "files.db"
        config = {
            "paths": [str(scan_dir)],
            "extensions": [".raw"],
            "case_sensitive": False,
            "recursive": True,
            "skip_dirs": [],
            "database": str(db_path),
        }
        (project_root / "config.yaml").write_text(yaml.dump(config))

        run_scan(project_root=project_root)
        run_hash(project_root=project_root)

        conn = open_database(db_path)
        assert count_total_files(conn) == 3

        groups = build_duplicate_groups(conn)
        assert len(groups) == 1  # one group of 3 identical files

        folder_stats = compute_folder_stats(groups)
        assert len(folder_stats) == 1
        assert folder_stats[0].folder == "photos"
        assert folder_stats[0].duplicate_count == 3

        # Select the only folder — last-copy protection must keep one
        plan = plan_deletions(selected_folders=["photos"], duplicate_groups=groups)
        assert len(plan.deletions) == 2
        assert len(plan.protected_paths) == 1
        assert plan.protected_paths[0] == "photos/IMG_001.raw"  # alphabetically first

        result = execute_deletions(conn=conn, base_path=scan_dir.resolve(), plan=plan)
        assert result.deleted_count == 2
        assert result.failed_count == 0

        # Verify exactly one file survives on disk
        remaining = list(photos.iterdir())
        assert len(remaining) == 1
        assert remaining[0].name == "IMG_001.raw"
        assert remaining[0].read_bytes() == content

        # Verify DB has exactly one record
        assert count_total_files(conn) == 1
        conn.close()

    def test_folder_ranking_order(self, tmp_path):
        """Verify folder stats are sorted by duplicate count descending."""
        project_root, scan_dir, db_path = _create_test_project(tmp_path)

        run_scan(project_root=project_root)
        run_hash(project_root=project_root)

        conn = open_database(db_path)
        groups = build_duplicate_groups(conn)
        folder_stats = compute_folder_stats(groups)

        counts = [(s.folder, s.duplicate_count) for s in folder_stats]
        # backup2 and originals both have 3, backup1 has 2
        assert counts[0][1] >= counts[1][1] >= counts[2][1]
        assert counts[2] == ("backup1", 2)
        conn.close()
