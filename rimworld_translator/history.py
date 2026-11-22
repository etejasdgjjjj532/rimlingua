"""Local checkpoints with optional Git and a standard-library file backend.

Restore reads a saved project, backs up current changes and regenerates its mod.
It never checks out code, resets Git HEAD or removes unrelated workspace files.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from .core import Project, atomic_write, export_mod, export_shared, writable_destination
from .installation import owned_mod_files

MAX_PROJECT = 64 * 1024 * 1024
GIT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
FILE_ID = re.compile(r"file-[0-9a-f]{32}\Z")


@dataclass(frozen=True)
class SnapshotRecord:
    id: str
    time: str
    message: str
    backend: str


def _workspace(project_path: Path, *, validate_export: bool = True) -> tuple[Path, Project, list[str]]:
    if project_path.name != "project.json":
        raise ValueError("Snapshots require a dedicated project.json workspace")
    if any(part.is_symlink() for part in (project_path, *project_path.parents)):
        raise ValueError("Project workspace contains a symbolic link")
    folder = project_path.parent.resolve()
    project = Project.load(project_path)
    writable_destination(folder, Path(project.source))
    if any(folder.rglob(".gitattributes")):
        raise ValueError("Custom Git attributes are not supported in translation workspaces")
    repo = folder / ".git"
    if repo.is_symlink() or (repo.exists() and not repo.is_dir()):
        raise ValueError("Invalid project Git directory")
    if repo.exists() and any(path.is_symlink() for path in repo.rglob("*")):
        raise ValueError("Symbolic link inside Git metadata")
    if (repo / "info/attributes").exists():
        raise ValueError("Custom Git attributes are not supported")
    paths = [project_path.name]
    export = folder / "mod"
    if validate_export and export.exists():
        writable_destination(export, Path(project.source))
        owned_mod_files(export, project.package_id)
        paths.append("mod")
    return folder, project, paths


def _git(folder: Path):
    executable = shutil.which("git")
    if executable is None:
        return None
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull

    def run(*args: str, binary: bool = False):
        options = {"text": True, "encoding": "utf-8", "errors": "replace"} if not binary else {}
        result = subprocess.run([
            executable, "-c", "core.hooksPath=" + os.devnull,
            "-c", "commit.gpgSign=false", "-c", "core.fsmonitor=false",
            "-c", "core.attributesFile=" + os.devnull, "-C", str(folder), *args,
        ], env=env, capture_output=True, check=True, **options)
        return result.stdout if binary else result.stdout.strip()
    return run


def _check_repo(folder: Path, git) -> None:
    if Path(git("rev-parse", "--show-toplevel")).resolve() != folder:
        raise ValueError("Git repository must be the project workspace")


def _file_index(folder: Path) -> tuple[Path, list[dict]]:
    history = folder / ".history"
    index = history / "index.json"
    if any(part.is_symlink() for part in (history, *history.parents)):
        raise ValueError("Symbolic link in history directory")
    if history.exists() and (not history.is_dir() or any(path.is_symlink() for path in history.rglob("*"))):
        raise ValueError("Invalid history directory")
    if not index.exists():
        if history.exists() and any(history.iterdir()):
            raise ValueError("History folder is not owned by this editor")
        return history, []
    if index.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("History index is too large")
    data = json.loads(index.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("snapshots"), list):
        raise ValueError("Unsupported history index")
    records = data["snapshots"]
    if len(records) > 100000:
        raise ValueError("History contains too many snapshots")
    seen = set()
    for record in records:
        if not isinstance(record, dict) or not FILE_ID.fullmatch(str(record.get("id", ""))):
            raise ValueError("Invalid history snapshot ID")
        if record["id"] in seen or not all(isinstance(record.get(name), str) for name in ("time", "message", "digest")):
            raise ValueError("Invalid history record")
        datetime.fromisoformat(record["time"])
        seen.add(record["id"])
    return history, records


def _digest(folder: Path, paths: list[str]) -> str:
    digest = hashlib.sha256()
    files = [folder / "project.json"]
    if "mod" in paths:
        files.extend(folder / "mod" / relative for relative in owned_mod_files(folder / "mod"))
    for path in sorted(files):
        digest.update(path.relative_to(folder).as_posix().encode("utf-8") + b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def _file_snapshot(folder: Path, project_path: Path, paths: list[str], message: str) -> bool:
    history, records = _file_index(folder)
    digest = _digest(folder, paths)
    if records and records[-1]["digest"] == digest:
        return False
    revision = "file-" + uuid.uuid4().hex
    record = {"id": revision, "time": datetime.now(timezone.utc).isoformat(), "message": message, "digest": digest}
    atomic_write(history / "snapshots" / (revision + ".json.gz"), gzip.compress(project_path.read_bytes(), mtime=0))
    atomic_write(history / "index.json", (json.dumps({"schema": 1, "snapshots": [*records, record]},
                                                     ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return True


def snapshot(project_path: Path | str, message: str = "Save translation project", keep: int | None = None) -> bool:
    """Record a checkpoint; ``keep`` limits how many file-backend checkpoints are retained (see prune_snapshots)."""
    project_path = Path(project_path)
    if keep is not None:
        _check_keep(keep)
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Snapshot message is empty")
    folder, _, paths = _workspace(project_path)
    git = _git(folder)
    if git is None:
        made = _file_snapshot(folder, project_path, paths, message)
        if keep is not None:
            prune_snapshots(project_path, keep)
        return made
    if not (folder / ".git").exists():
        git("init")
    _check_repo(folder, git)
    for name, value in (("user.name", "Codex"), ("user.email", "codex@localhost")):
        try:
            git("config", "--local", "--get", name)
        except subprocess.CalledProcessError:
            git("config", "--local", name, value)
    git("add", "--", *paths)
    if not git("diff", "--cached", "--name-only", "--", *paths):
        return False
    git("commit", "--only", "-m", message, "--", *paths)
    return True


def _check_keep(keep) -> None:
    if type(keep) is not int or keep < 1:
        raise ValueError("Keep at least one backup generation")


def prune_snapshots(project_path: Path | str, keep: int) -> list[str]:
    """Delete all but the newest ``keep`` file-backend checkpoints; returns the removed IDs.

    Git checkpoints are never rewritten: deleting commits would rewrite the user's
    history, so only the standard-library backend (``.history``) is pruned.
    """
    _check_keep(keep)
    folder, _, _ = _workspace(Path(project_path), validate_export=False)
    history, records = _file_index(folder)
    if len(records) <= keep:
        return []
    removed, kept = records[:-keep], records[-keep:]
    atomic_write(history / "index.json", (json.dumps({"schema": 1, "snapshots": kept},
                                                     ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    for record in removed:
        (history / "snapshots" / (record["id"] + ".json.gz")).unlink(missing_ok=True)
    return [record["id"] for record in removed]


def list_snapshots(project_path: Path | str) -> list[SnapshotRecord]:
    """Newest first. Browsing never initializes a repository or makes a commit."""
    folder, _, _ = _workspace(Path(project_path), validate_export=False)
    _, files = _file_index(folder)
    records = [SnapshotRecord(item["id"], item["time"], item["message"], "file") for item in files]
    git = _git(folder)
    if git is not None and (folder / ".git").exists():
        _check_repo(folder, git)
        try:
            git("rev-parse", "--verify", "HEAD")
        except subprocess.CalledProcessError:
            return sorted(records, key=lambda item: datetime.fromisoformat(item.time).timestamp(), reverse=True)
        output = git("log", "--format=%H%x00%cI%x00%B%x00", "--", "project.json", "mod")
        fields = output.split("\0")
        for index in range(0, len(fields) - 2, 3):
            revision, time, message = (field.strip() for field in fields[index:index + 3])
            if not GIT_ID.fullmatch(revision):
                raise ValueError("Invalid Git history record")
            records.append(SnapshotRecord(revision, time, message, "git"))
    return sorted(records, key=lambda item: datetime.fromisoformat(item.time).timestamp(), reverse=True)


def _saved_project(folder: Path, revision: str, records: list[SnapshotRecord]) -> bytes:
    record = next((item for item in records if item.id == revision), None)
    if record is None:
        raise ValueError("Snapshot was not found in this project")
    if record.backend == "file":
        history, _ = _file_index(folder)
        with gzip.open(history / "snapshots" / (revision + ".json.gz"), "rb") as stream:
            payload = stream.read(MAX_PROJECT + 1)
    else:
        git = _git(folder)
        if git is None:
            raise ValueError("Git is required to read an existing Git checkpoint")
        payload = git("show", revision + ":project.json", binary=True)
    if len(payload) > MAX_PROJECT:
        raise ValueError("Saved project is too large")
    return payload


@dataclass
class RestoreReport:
    """Outcome of a restore. ``output_updated`` is False when the restored project
    could not produce output; the previous ``mod`` folder is then kept unchanged."""
    project: Project
    output_updated: bool
    notices: list[str]


def _regenerate(project: Project, target: Path) -> list[str]:
    """Build output the way the editor does: the shared formal set for multi-version
    projects, the single-version exporter otherwise."""
    if project.version_profiles:
        return export_shared(project, target).warnings
    return export_mod(project, target)


def restore_snapshot(project_path: Path | str, revision: str, export_folder: Path | str | None = None) -> Project:
    """Restore a validated record ID, preserving HEAD and unrelated files (see restore_snapshot_report)."""
    return restore_snapshot_report(project_path, revision, export_folder).project


def restore_snapshot_report(project_path: Path | str, revision: str, export_folder: Path | str | None = None) -> RestoreReport:
    """Restore a validated record ID, preserving HEAD and unrelated files.

    Current changes become a checkpoint first. If current content is already a
    checkpoint, that existing checkpoint is the backup and no extra commit is
    needed. Generated mod replacement and project writes roll back on failure.
    When the restored project cannot produce output (for example no version is
    ready), the project is still restored and the current output folder is kept.
    The output goes to ``export_folder`` when given (the caller's checked output folder), else to the project's
    own ``output_folder`` setting, else to ``<project folder>/mod``. A custom folder that already has content
    must be an unmodified export of this project, since the whole folder is replaced.
    """
    if not isinstance(revision, str) or not (GIT_ID.fullmatch(revision) or FILE_ID.fullmatch(revision)):
        raise ValueError("Invalid snapshot ID; select an ID from the project history")
    project_path = Path(project_path)
    folder, current_project, _ = _workspace(project_path)
    records = list_snapshots(project_path)
    payload = _saved_project(folder, revision, records)
    chosen = export_folder if export_folder is not None else (current_project.output_folder or None)
    export = Path(chosen).absolute() if chosen else folder / "mod"
    if export != folder / "mod":
        resolved = export.resolve()
        if resolved == folder or resolved in folder.parents or folder in resolved.parents:
            raise ValueError("Output folder overlaps the project folder")
        writable_destination(export, Path(current_project.source))
        if export.exists() and any(export.iterdir()):
            owned_mod_files(export, current_project.package_id)
    export.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=folder) as temporary, \
            tempfile.TemporaryDirectory(prefix=".restore-", dir=export.parent) as swap:
        staging = Path(temporary)
        swap_dir = Path(swap)
        candidate = staging / "project.json"
        atomic_write(candidate, payload)
        restored = Project.load(candidate)
        writable_destination(folder, Path(restored.source))
        # Where output goes is this machine's current setting, not whatever the old snapshot remembered.
        restored.output_folder = current_project.output_folder
        restored.save(candidate)
        try:
            notices = _regenerate(restored, swap_dir / "mod")
            output_updated = True
        except ValueError as exc:
            output_updated = False
            notices = ["復元した版からは翻訳MODを出力できないため、今の mod フォルダーをそのまま残しました: " + str(exc)]
        snapshot(project_path, "Before restore " + revision[:16])
        current = project_path.read_bytes()
        old_mod = swap_dir / "previous-mod"
        moved_old = False
        installed_new = False
        try:
            atomic_write(project_path, candidate.read_bytes())
            if output_updated:
                if export.exists():
                    os.replace(export, old_mod)
                    moved_old = True
                os.replace(swap_dir / "mod", export)
                installed_new = True
        except BaseException:
            atomic_write(project_path, current)
            if installed_new:
                os.replace(export, swap_dir / "failed-mod")
            if moved_old:
                os.replace(old_mod, export)
            raise
    return RestoreReport(restored, output_updated, notices)
