"""Interactive duplicate folder cleanup for raw-deduplicator_v2.

Analyzes duplicate files by folder, provides an interactive TUI for
selecting which folders' duplicates to remove, and executes deletion
with last-copy safety protection.
"""

import collections.abc
import dataclasses
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from app.database import delete_files, iter_hashed_files_with_id

_GB: int = 1024**3
_MB: int = 1024**2
_KB: int = 1024


def _format_size(size: int) -> str:
    """Format a byte count with auto-selected unit.

    Args:
        size: The size in bytes.

    Returns:
        A human-readable string like "1.50 GB" or "500 B".
    """
    if size >= _GB:
        return f"{size / _GB:.2f} GB"
    if size >= _MB:
        return f"{size / _MB:.2f} MB"
    if size >= _KB:
        return f"{size / _KB:.2f} KB"
    return f"{size} B"


@dataclasses.dataclass(frozen=True)
class DuplicateFile:
    """A file that belongs to a duplicate group.

    Attributes:
        file_id: The database row ID.
        rel_path: Path relative to the scan root.
        file_size: File size in bytes.
        group_key: The duplicate group key (file_size_md5_sha256).
        folder: The directory part of rel_path.
    """

    file_id: int
    rel_path: str
    file_size: int
    group_key: str
    folder: str


@dataclasses.dataclass(frozen=True)
class FolderStats:
    """Statistics about duplicate files in a folder.

    Attributes:
        folder: The folder path relative to the scan root.
        duplicate_count: Number of files in this folder that have copies elsewhere.
        reclaimable_bytes: Total size of those duplicate files.
        files: The duplicate files in this folder.
    """

    folder: str
    duplicate_count: int
    reclaimable_bytes: int
    files: list[DuplicateFile]


@dataclasses.dataclass(frozen=True)
class FileDeletion:
    """A file planned for deletion.

    Attributes:
        file_id: The database row ID.
        rel_path: Path relative to the scan root.
        file_size: File size in bytes.
        surviving_copy: rel_path of a copy that will survive.
    """

    file_id: int
    rel_path: str
    file_size: int
    surviving_copy: str


@dataclasses.dataclass(frozen=True)
class DeletionPlan:
    """Plan for which files to delete.

    Attributes:
        deletions: Files to delete from disk and database.
        protected_paths: rel_paths of files kept by last-copy protection.
        total_bytes: Total bytes that will be freed.
    """

    deletions: list[FileDeletion]
    protected_paths: list[str]
    total_bytes: int


@dataclasses.dataclass(frozen=True)
class DeletionResult:
    """Result of executing a deletion plan.

    Attributes:
        deleted_count: Number of files successfully deleted.
        deleted_bytes: Total bytes freed.
        failed_count: Number of files that could not be deleted.
        failed_paths: rel_paths of files that failed to delete.
    """

    deleted_count: int
    deleted_bytes: int
    failed_count: int
    failed_paths: list[str]


def build_duplicate_groups(conn: sqlite3.Connection) -> dict[str, list[DuplicateFile]]:
    """Build duplicate groups from hashed files in the database.

    Groups files by (file_size, md5_hash, sha256_hash). Only groups with
    2 or more files are returned.

    Args:
        conn: An open SQLite connection to the files database.

    Returns:
        A dict mapping group keys to lists of DuplicateFile objects.
        Only groups with 2+ files are included.
    """
    index: dict[str, list[DuplicateFile]] = defaultdict(list)

    cursor: sqlite3.Cursor = iter_hashed_files_with_id(conn)
    for row in cursor:
        file_id: int = row[0]
        file_size: int = row[1]
        md5_hash: str = row[2]
        sha256_hash: str = row[3]
        rel_path: str = row[4]

        key: str = f"{file_size}_{md5_hash}_{sha256_hash}"
        folder: str = str(PurePosixPath(rel_path).parent)

        index[key].append(
            DuplicateFile(
                file_id=file_id,
                rel_path=rel_path,
                file_size=file_size,
                group_key=key,
                folder=folder,
            )
        )

    return {k: v for k, v in index.items() if len(v) > 1}


def compute_folder_stats(duplicate_groups: dict[str, list[DuplicateFile]]) -> list[FolderStats]:
    """Compute per-folder statistics from duplicate groups.

    Aggregates duplicate files by folder and sorts by duplicate count
    descending, with reclaimable bytes as a secondary sort key.

    Args:
        duplicate_groups: Dict mapping group keys to lists of DuplicateFile.

    Returns:
        A list of FolderStats sorted by duplicate_count descending,
        then reclaimable_bytes descending.
    """
    folder_files: dict[str, list[DuplicateFile]] = defaultdict(list)

    for files in duplicate_groups.values():
        for dup_file in files:
            folder_files[dup_file.folder].append(dup_file)

    stats: list[FolderStats] = []
    for folder, files in folder_files.items():
        stats.append(
            FolderStats(
                folder=folder,
                duplicate_count=len(files),
                reclaimable_bytes=sum(f.file_size for f in files),
                files=files,
            )
        )

    stats.sort(key=lambda s: (-s.duplicate_count, -s.reclaimable_bytes))
    return stats


def _aggregate_tree_stats(
    children: dict[str, Any],
    stats_by_folder: dict[str, FolderStats],
    path_so_far: str,
    aggregated: dict[str, tuple[int, int]],
) -> tuple[int, int]:
    """Recursively compute aggregated duplicate stats for every tree node.

    Each node's aggregated stats include its own direct duplicates (if any)
    plus all descendant duplicates. Results are stored in the aggregated dict.

    Args:
        children: Dict mapping child name to its sub-children dict.
        stats_by_folder: Lookup from full folder path to FolderStats.
        path_so_far: Accumulated path prefix for lookup.
        aggregated: Accumulator mapping folder path to (total_dupes, total_bytes).

    Returns:
        Tuple of (total_duplicate_count, total_reclaimable_bytes) for this subtree.
    """
    total_dupes: int = 0
    total_bytes: int = 0

    # Include own direct stats if this folder has duplicates
    if path_so_far in stats_by_folder:
        s: FolderStats = stats_by_folder[path_so_far]
        total_dupes += s.duplicate_count
        total_bytes += s.reclaimable_bytes

    # Recurse into children
    for name, sub_children in children.items():
        full_path: str = f"{path_so_far}/{name}" if path_so_far else name
        child_dupes: int
        child_bytes: int
        child_dupes, child_bytes = _aggregate_tree_stats(sub_children, stats_by_folder, full_path, aggregated)
        total_dupes += child_dupes
        total_bytes += child_bytes

    if path_so_far:
        aggregated[path_so_far] = (total_dupes, total_bytes)

    return total_dupes, total_bytes


def build_folder_tree_entries(
    folder_stats: list[FolderStats],
    expanded: set[str],
) -> tuple[list[str], dict[int, str], dict[str, int], set[str]]:
    """Build tree-formatted menu entries from folder stats.

    Creates ASCII tree lines suitable for use in a TerminalMenu, with
    children sorted alphabetically at each level. Every folder shows
    aggregated duplicate count and reclaimable size (including all
    descendants). Folders not in the expanded set are shown collapsed
    (children hidden). Visual indicators show expand/collapse state.

    Args:
        folder_stats: List of FolderStats to build the tree from.
        expanded: Set of folder paths that should be shown expanded.

    Returns:
        A tuple of (entries, index_to_folder, folder_to_index, expandable):
        - entries: list of display strings
        - index_to_folder: every entry index mapped to its folder path
        - folder_to_index: folder path mapped to its entry index
        - expandable: set of folder paths that have children (can expand)
    """
    stats_by_folder: dict[str, FolderStats] = {s.folder: s for s in folder_stats}

    entries: list[str] = []
    index_to_folder: dict[int, str] = {}
    folder_to_index: dict[str, int] = {}
    expandable: set[str] = set()

    # Handle root-level folder "." as first entry if present
    if "." in stats_by_folder:
        s: FolderStats = stats_by_folder["."]
        entries.append(f"./  ({s.duplicate_count} duplicates, {_format_size(s.reclaimable_bytes)})")
        index_to_folder[0] = "."
        folder_to_index["."] = 0

    # Build nested dict tree from non-root folder paths
    tree: dict[str, Any] = {}
    for stats in folder_stats:
        if stats.folder == ".":
            continue
        parts: tuple[str, ...] = PurePosixPath(stats.folder).parts
        node: dict[str, Any] = tree
        for part in parts:
            if part not in node:
                node[part] = {}
            node = node[part]

    # Compute aggregated stats for every node (including intermediates)
    aggregated: dict[str, tuple[int, int]] = {}
    _aggregate_tree_stats(tree, stats_by_folder, "", aggregated)

    _flatten_tree_entries(
        children=tree,
        stats_by_folder=stats_by_folder,
        aggregated=aggregated,
        expanded=expanded,
        path_so_far="",
        prefix="",
        entries=entries,
        index_to_folder=index_to_folder,
        folder_to_index=folder_to_index,
        expandable=expandable,
    )

    return entries, index_to_folder, folder_to_index, expandable


def _flatten_tree_entries(
    children: dict[str, Any],
    stats_by_folder: dict[str, FolderStats],
    aggregated: dict[str, tuple[int, int]],
    expanded: set[str],
    path_so_far: str,
    prefix: str,
    entries: list[str],
    index_to_folder: dict[int, str],
    folder_to_index: dict[str, int],
    expandable: set[str],
) -> None:
    """Recursively flatten tree into menu entries with ASCII connectors.

    Every folder shows its aggregated stats. All entries are recorded
    in index_to_folder so every folder is navigable and selectable.
    Folders with children show expand/collapse indicators and only
    recurse into children when in the expanded set.

    Args:
        children: Dict mapping child name to its sub-children dict.
        stats_by_folder: Lookup from full folder path to FolderStats.
        aggregated: Lookup from folder path to aggregated (dupes, bytes).
        expanded: Set of folder paths currently expanded.
        path_so_far: Accumulated path prefix for stats lookup.
        prefix: Current indentation prefix for rendering.
        entries: Accumulator list for menu entry strings.
        index_to_folder: Accumulator mapping entry index to folder path.
        folder_to_index: Accumulator mapping folder path to entry index.
        expandable: Accumulator for folders that have children.
    """
    sorted_names: list[str] = sorted(children.keys())
    for i, name in enumerate(sorted_names):
        is_last: bool = i == len(sorted_names) - 1
        connector: str = "└── " if is_last else "├── "

        full_path: str = f"{path_so_far}/{name}" if path_so_far else name

        has_children: bool = len(children[name]) > 0
        if has_children:
            expandable.add(full_path)

        # Every entry is mapped (not just those with direct duplicates)
        idx: int = len(entries)
        index_to_folder[idx] = full_path
        folder_to_index[full_path] = idx

        # Expand/collapse indicator for folders with children
        indicator: str = ""
        if has_children:
            indicator = "▾ " if full_path in expanded else "▸ "

        # Show aggregated stats (own + all descendants)
        annotation: str = ""
        if full_path in aggregated:
            dupes: int = aggregated[full_path][0]
            size: int = aggregated[full_path][1]
            annotation = f"  ({dupes} duplicates, {_format_size(size)})"

        entries.append(f"{prefix}{connector}{indicator}{name}/{annotation}")

        # Only recurse into children if this folder is expanded
        if has_children and full_path in expanded:
            extension: str = "    " if is_last else "│   "
            _flatten_tree_entries(
                children=children[name],
                stats_by_folder=stats_by_folder,
                aggregated=aggregated,
                expanded=expanded,
                path_so_far=full_path,
                prefix=prefix + extension,
                entries=entries,
                index_to_folder=index_to_folder,
                folder_to_index=folder_to_index,
                expandable=expandable,
            )


def _expand_selected_folders(
    selected_folders: list[str],
    all_folders_with_duplicates: set[str],
) -> list[str]:
    """Expand parent folder selections to include descendant folders.

    For each selected folder, includes the folder itself (if it has
    direct duplicates) plus all folders in all_folders_with_duplicates
    that are descendants of the selected folder.

    Args:
        selected_folders: Folder paths selected by the user.
        all_folders_with_duplicates: Set of all folder paths that have duplicates.

    Returns:
        Deduplicated sorted list of folder paths to pass to plan_deletions.
    """
    result: set[str] = set()
    for folder in selected_folders:
        if folder in all_folders_with_duplicates:
            result.add(folder)
        for candidate in all_folders_with_duplicates:
            if candidate.startswith(folder + "/"):
                result.add(candidate)
    return sorted(result)


def plan_deletions(
    selected_folders: list[str],
    duplicate_groups: dict[str, list[DuplicateFile]],
) -> DeletionPlan:
    """Plan which files to delete based on selected folders.

    For each duplicate group, files in selected folders are marked for
    deletion. If ALL copies of a group are in selected folders, the
    alphabetically first copy is protected (last-copy safety).

    Args:
        selected_folders: List of folder names selected for cleanup.
        duplicate_groups: Dict mapping group keys to lists of DuplicateFile.

    Returns:
        A DeletionPlan with files to delete, protected paths, and total bytes.
    """
    selected_set: set[str] = set(selected_folders)
    deletions: list[FileDeletion] = []
    protected_paths: list[str] = []

    for files in duplicate_groups.values():
        in_selected: list[DuplicateFile] = [f for f in files if f.folder in selected_set]
        in_safe: list[DuplicateFile] = [f for f in files if f.folder not in selected_set]

        if not in_selected:
            continue

        if in_safe:
            surviving: str = sorted(in_safe, key=lambda f: f.rel_path)[0].rel_path
            deletions.extend(
                FileDeletion(
                    file_id=dup_file.file_id,
                    rel_path=dup_file.rel_path,
                    file_size=dup_file.file_size,
                    surviving_copy=surviving,
                )
                for dup_file in in_selected
            )
        else:
            sorted_files: list[DuplicateFile] = sorted(in_selected, key=lambda f: f.rel_path)
            protected_path: str = sorted_files[0].rel_path
            protected_paths.append(protected_path)
            deletions.extend(
                FileDeletion(
                    file_id=dup_file.file_id,
                    rel_path=dup_file.rel_path,
                    file_size=dup_file.file_size,
                    surviving_copy=protected_path,
                )
                for dup_file in sorted_files[1:]
            )

    total_bytes: int = sum(d.file_size for d in deletions)

    return DeletionPlan(
        deletions=deletions,
        protected_paths=protected_paths,
        total_bytes=total_bytes,
    )


def execute_deletions(
    conn: sqlite3.Connection,
    base_path: Path,
    plan: DeletionPlan,
) -> DeletionResult:
    """Execute file deletions from disk and database.

    For each file in the deletion plan, removes it from disk (if present)
    and from the database. Files already missing from disk are still
    cleaned up in the database. Files that cannot be deleted due to
    OS errors are tracked as failures.

    Args:
        conn: An open SQLite connection to the files database.
        base_path: The resolved base directory that rel_path values are relative to.
        plan: The deletion plan to execute.

    Returns:
        A DeletionResult with counts and paths of deleted and failed files.
    """
    # Pre-flight safety: verify every surviving copy exists on disk.
    # Without this, we could delete a file whose "surviving copy" is
    # already gone from disk (but still in the DB), causing data loss.
    surviving_copies: set[str] = {d.surviving_copy for d in plan.deletions}
    missing_survivors: list[str] = [rel_path for rel_path in sorted(surviving_copies) if not (base_path / rel_path).exists()]
    if missing_survivors:
        print("\n  ABORT: Surviving copies missing from disk — deletion blocked to prevent data loss.")
        print(f"  {len(missing_survivors)} surviving copies not found:\n")
        for rel_path in missing_survivors[:20]:
            print(f"    {rel_path}")
        if len(missing_survivors) > 20:
            print(f"    ... +{len(missing_survivors) - 20} more")
        print("\n  Run 'just scan-update' to remove stale database entries, then retry.")
        return DeletionResult(
            deleted_count=0,
            deleted_bytes=0,
            failed_count=len(plan.deletions),
            failed_paths=[d.rel_path for d in plan.deletions],
        )

    deleted_ids: list[int] = []
    deleted_bytes: int = 0
    failed_paths: list[str] = []
    total: int = len(plan.deletions)

    for i, file_del in enumerate(plan.deletions, start=1):
        full_path: Path = base_path / file_del.rel_path
        size_str: str = _format_size(file_del.file_size)
        print(f"  [{i}/{total}] Deleting {file_del.rel_path}  ({size_str})")

        try:
            full_path.unlink(missing_ok=True)
        except OSError as err:
            print(f"  WARNING: Could not delete {full_path}: {err}", file=sys.stderr)
            failed_paths.append(file_del.rel_path)
            continue

        deleted_ids.append(file_del.file_id)
        deleted_bytes += file_del.file_size

    if deleted_ids:
        delete_files(conn, deleted_ids)
        conn.commit()

    return DeletionResult(
        deleted_count=len(deleted_ids),
        deleted_bytes=deleted_bytes,
        failed_count=len(failed_paths),
        failed_paths=failed_paths,
    )


def print_dry_run_report(plan: DeletionPlan) -> None:
    """Print a dry-run report of planned deletions.

    Shows each file to be deleted, where a surviving copy lives,
    totals, and any files protected by last-copy safety.

    Args:
        plan: The deletion plan to report on.
    """
    folder_count: int = len({d.rel_path.rsplit("/", 1)[0] if "/" in d.rel_path else "." for d in plan.deletions})
    print(f"\nFiles to delete ({folder_count} folders selected):\n")

    for file_del in sorted(plan.deletions, key=lambda d: d.rel_path):
        size_str: str = _format_size(file_del.file_size)
        print(f"  {file_del.rel_path}  ({size_str})  -- kept in: {file_del.surviving_copy}")

    print(f"\n  Total: {len(plan.deletions)} files, {_format_size(plan.total_bytes)}")

    if plan.protected_paths:
        print(f"\n  Warning: {len(plan.protected_paths)} files skipped (last copy protection)")
        for path in sorted(plan.protected_paths):
            print(f"    {path}")

    print()


def _build_folder_detail_lines(
    folder: str,
    stats_by_folder: dict[str, FolderStats],
    duplicate_groups: dict[str, list[DuplicateFile]],
) -> list[str]:
    """Build detail lines showing duplicate files in a folder with all copy paths.

    For each unique duplicate group present in the folder, shows the filename,
    size, copy count, and all copy paths. Sorted by copy count descending,
    then by filename ascending.

    Args:
        folder: The folder path to show details for.
        stats_by_folder: Lookup from folder path to FolderStats.
        duplicate_groups: All duplicate groups for copy lookup.

    Returns:
        List of formatted strings for display.
    """
    if folder not in stats_by_folder:
        return [f"No duplicate files in {folder}/"]

    folder_stat: FolderStats = stats_by_folder[folder]

    seen_groups: set[str] = set()
    file_details: list[tuple[int, str, int, list[str]]] = []
    for f in folder_stat.files:
        if f.group_key in seen_groups:
            continue
        seen_groups.add(f.group_key)
        group: list[DuplicateFile] = duplicate_groups[f.group_key]
        copy_paths: list[str] = sorted(df.rel_path for df in group)
        filename: str = PurePosixPath(f.rel_path).name
        file_details.append((len(copy_paths), filename, f.file_size, copy_paths))

    file_details.sort(key=lambda x: (-x[0], x[1]))

    lines: list[str] = []
    lines.append(f"Duplicate files in {folder}/ ({len(file_details)} files):")
    lines.append("")
    for copy_count, filename, file_size, paths in file_details:
        size_str: str = _format_size(file_size)
        lines.append(f"  {filename}  ({size_str}) — {copy_count} copies:")
        lines.extend(f"    {path}" for path in paths)
        lines.append("")

    return lines


def _make_status_callback(
    entry_to_folder: dict[str, str],
    stats_by_folder: dict[str, FolderStats],
) -> "collections.abc.Callable[[str], str]":
    """Create a status bar callback that shows files for the highlighted folder.

    Args:
        entry_to_folder: Mapping from entry display string to folder path.
        stats_by_folder: Lookup from folder path to FolderStats.

    Returns:
        A callable that receives an entry string and returns a status string
        listing up to 10 duplicate filenames in that folder.
    """

    def callback(entry_text: str) -> str:
        if entry_text not in entry_to_folder:
            return ""
        folder_path: str = entry_to_folder[entry_text]
        if folder_path not in stats_by_folder:
            return ""
        filenames: list[str] = sorted(PurePosixPath(f.rel_path).name for f in stats_by_folder[folder_path].files)
        max_files: int = 10
        shown: str = ", ".join(filenames[:max_files])
        if len(filenames) > max_files:
            shown += f" ... +{len(filenames) - max_files} more"
        return f"Files: {shown}"

    return callback


def _result_to_folder_paths(
    result: int | tuple[int, ...] | None,
    index_to_folder: dict[int, str],
) -> set[str]:
    """Convert TerminalMenu result indices to a set of folder paths.

    Args:
        result: The return value from TerminalMenu.show().
        index_to_folder: Mapping from entry index to folder path.

    Returns:
        Set of folder path strings for the selected indices.
    """
    if result is None:
        return set()
    if isinstance(result, int):
        indices: tuple[int, ...] = (result,)
    else:
        indices = result
    return {index_to_folder[i] for i in indices if i in index_to_folder}


def show_folder_menu(
    folder_stats: list[FolderStats],
    duplicate_groups: dict[str, list[DuplicateFile]],
) -> list[str] | None:
    """Show an interactive folder selection menu as an expandable ASCII tree.

    Displays folders in a tree hierarchy with ASCII connectors, sorted
    alphabetically at each level. Folders start collapsed and can be
    expanded/collapsed with Enter. Space toggles folder selection.
    Tab shows duplicate file details for the highlighted folder.
    Pressing d/D proceeds with deletion of selected folders.

    Keys:
        Space: toggle folder selection.
        Enter: expand/collapse folder.
        Tab: show duplicate file details for highlighted folder.
        d/D: confirm selection and proceed to deletion.
        Escape/q: cancel.

    Args:
        folder_stats: List of FolderStats to display.
        duplicate_groups: All duplicate groups for file detail lookup.

    Returns:
        List of selected folder name strings, or None if cancelled/empty.
    """
    if not sys.stdout.isatty():
        print("ERROR: Cleanup requires an interactive terminal.", file=sys.stderr)
        sys.exit(1)

    from simple_term_menu import TerminalMenu

    stats_by_folder: dict[str, FolderStats] = {s.folder: s for s in folder_stats}
    expanded: set[str] = set()
    cursor_folder: str | None = None
    selected_paths: set[str] = set()

    while True:
        entries: list[str]
        idx_to_folder: dict[int, str]
        folder_to_idx: dict[str, int]
        expandable: set[str]
        entries, idx_to_folder, folder_to_idx, expandable = build_folder_tree_entries(folder_stats, expanded)

        entry_to_folder: dict[str, str] = {entries[idx]: folder for idx, folder in idx_to_folder.items()}

        # Restore cursor position
        cursor_pos: int | None = folder_to_idx.get(cursor_folder) if cursor_folder else None

        # Restore selections as indices
        preselected: list[int] = [folder_to_idx[f] for f in selected_paths if f in folder_to_idx]

        menu = TerminalMenu(
            entries,
            title="Select folders to remove duplicates from:",
            multi_select=True,
            multi_select_keys=(" ",),
            accept_keys=("enter", "tab", "d", "D"),
            multi_select_select_on_accept=False,
            multi_select_empty_ok=True,
            show_multi_select_hint=True,
            show_multi_select_hint_text=("<space>: select  <enter>: expand/collapse  <tab>: details  <d>: delete selected"),
            cursor_index=cursor_pos,
            preselected_entries=preselected or None,
            status_bar=_make_status_callback(entry_to_folder, stats_by_folder),
        )

        result: int | tuple[int, ...] | None = menu.show()
        accept_key: str = menu.chosen_accept_key

        if not accept_key:  # Escape/q → empty string
            return None

        # Save cursor position — _view.active_menu_index is the only way to
        # retrieve the cursor position from simple_term_menu after show().
        raw_cursor: int = menu._view.active_menu_index
        cursor_folder = idx_to_folder.get(raw_cursor)

        # Save current selections as folder paths
        selected_paths = _result_to_folder_paths(result, idx_to_folder)

        if accept_key == "enter":
            # Toggle expand/collapse
            if cursor_folder and cursor_folder in expandable:
                expanded.symmetric_difference_update({cursor_folder})
            continue

        if accept_key == "tab":
            # Show duplicate file details for highlighted folder
            if cursor_folder:
                detail_lines: list[str] = _build_folder_detail_lines(cursor_folder, stats_by_folder, duplicate_groups)
                print()
                for line in detail_lines:
                    print(line)
                input("Press Enter to return.")
            continue

        # accept_key is "d" or "D" → proceed with deletion
        if not selected_paths:
            return None

        all_with_dupes: set[str] = {s.folder for s in folder_stats}
        return _expand_selected_folders(sorted(selected_paths), all_with_dupes)


def run_cleanup_interactive(conn: sqlite3.Connection, base_path: Path) -> None:
    """Run the full interactive cleanup workflow.

    Builds duplicate groups, shows folder analysis, presents the TUI
    menu for folder selection, shows a dry-run report, and executes
    deletion after user confirmation.

    Args:
        conn: An open SQLite connection to the files database.
        base_path: The resolved base directory that rel_path values are relative to.
    """
    print("Analyzing duplicate files by folder...")
    groups: dict[str, list[DuplicateFile]] = build_duplicate_groups(conn)

    if not groups:
        print("No duplicates found.")
        return

    folder_stats: list[FolderStats] = compute_folder_stats(groups)
    print(f"Found {len(groups)} duplicate groups across {len(folder_stats)} folders.\n")

    while True:
        selected: list[str] | None = show_folder_menu(folder_stats, groups)

        if selected is None:
            print("Cancelled.")
            return

        plan: DeletionPlan = plan_deletions(
            selected_folders=selected,
            duplicate_groups=groups,
        )

        if not plan.deletions:
            print("No files to delete in selected folders.")
            continue

        print_dry_run_report(plan)

        answer: str = input("Proceed with deletion? [y/N] ")
        if answer.strip().lower() != "y":
            print("Returning to folder selection...\n")
            continue

        result: DeletionResult = execute_deletions(conn=conn, base_path=base_path, plan=plan)

        print(f"\nDeleted: {result.deleted_count} files ({_format_size(result.deleted_bytes)})")
        if result.failed_count > 0:
            print(f"Failed:  {result.failed_count} files (see warnings above)")
        if plan.protected_paths:
            print(f"Skipped: {len(plan.protected_paths)} files (last copy protection)")

        # Refresh duplicate groups — some may no longer exist after deletion
        print("\nRefreshing duplicate analysis...")
        groups = build_duplicate_groups(conn)
        if not groups:
            print("\nNo more duplicates remaining.")
            return
        folder_stats = compute_folder_stats(groups)
        print(f"\n{len(groups)} duplicate groups remaining across {len(folder_stats)} folders.\n")
