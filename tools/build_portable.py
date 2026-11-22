"""Build and validate a native PyInstaller onedir portable release.

No source MOD, game install, translation workspace, or user's Git data is read.
The executable contains Python and Qt; Git is an optional external enhancement.
"""
import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rimworld_translator.version import __version__
from rimworld_translator.runtime import runtime_evidence

APP_NAME = "RimWorldTranslationEditor"


def native_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    raise ValueError("Portable builds currently support native Windows and Linux only.")


def validate_root(root: Path) -> Path:
    root = root.resolve()
    if ((root / "About/About.xml").is_file() or (root / "Data/Core").is_dir()
            or (root / "Defs").is_dir()):
        raise ValueError("Build root must be the editor repository, never a game or source MOD.")
    if not (root / "pyproject.toml").is_file():
        raise ValueError("Build root does not contain pyproject.toml.")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    if project.get("project", {}).get("name") != "rimworld-translation-editor":
        raise ValueError("Build root is not rimworld-translation-editor.")
    for name in ("rimworld_translator/gui.py", "packaging/portable.spec", "packaging/launcher.py"):
        if not (root / name).is_file():
            raise ValueError(f"Build root is missing {name}.")
    return root


def validate_bundle(bundle: Path) -> None:
    """Reject redistributable game/MOD content and private project workspaces."""
    forbidden_directories = {"defs", "about", "languages", ".git", ".venv", "steamapps"}
    forbidden_files = {"project.json", "assembly-csharp.dll", "rimworldwin64.exe", "rimworldlinux"}
    resolved = bundle.resolve()
    for path in bundle.rglob("*"):
        parts = {part.casefold() for part in path.relative_to(bundle).parts}
        if parts & forbidden_directories or path.name.casefold() in forbidden_files:
            raise ValueError(f"Private/game/MOD content cannot be redistributed: {path.relative_to(bundle)}")
        if path.is_symlink() and not path.resolve().is_relative_to(resolved):
            raise ValueError(f"Bundle contains an external symlink: {path.relative_to(bundle)}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_archive(bundle: Path, output: Path, target: str, architecture: str,
                   *, wine_preview: bool = False) -> Path:
    validate_bundle(bundle)
    base = f"rimworld-translation-editor-{__version__}-{target}-{architecture}"
    if wine_preview:
        base += '-wine-preview'
    if target == "windows":
        archive = output / f"{base}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as stream:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    stream.write(path, path.relative_to(bundle.parent).as_posix())
    elif target == "linux":
        archive = output / f"{base}.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(bundle, arcname=bundle.name)
    else:
        raise ValueError("Only native Windows and Linux archives are supported.")
    return archive


def collect_licenses(bundle: Path, root: Path) -> list[dict]:
    """Copy installed dependency license files and a machine-readable inventory."""
    from packaging.requirements import Requirement

    destination = bundle / "licenses"
    destination.mkdir(exist_ok=True)
    pending = ["PySide6", "lxml", "dnfile", "polib", "pyinstaller"]
    seen = set()
    inventory = []
    while pending:
        name = pending.pop()
        distribution = metadata.distribution(name)
        canonical = distribution.metadata["Name"].lower().replace("_", "-")
        if canonical in seen:
            continue
        seen.add(canonical)
        item = {"name": distribution.metadata["Name"], "version": distribution.version,
                "license": distribution.metadata.get("License-Expression")
                           or distribution.metadata.get("License") or "See included license files",
                "files": []}
        for file in distribution.files or []:
            lower = file.name.lower()
            # Keep license texts; copying only explicitly licensed files avoids
            # accidentally including package resources or developer workspaces.
            if lower.startswith(("license", "copying", "copyright", "notice")):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    target = destination / canonical / str(file).replace("\\", "/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    item["files"].append(target.relative_to(bundle).as_posix())
        inventory.append(item)
        for requirement in distribution.requires or []:
            parsed = Requirement(requirement)
            if parsed.marker is None or parsed.marker.evaluate():
                pending.append(parsed.name)
    shutil.copyfile(root / "rimworld_translator/assets/flags/LICENSE", destination / "flag-icons-MIT.txt")
    shutil.copyfile(root / "LICENSE", destination / "RimWorldTranslationEditor-MPL-2.0.txt")
    shutil.copyfile(root / "packaging/THIRD_PARTY_NOTICES.md", destination / "THIRD_PARTY_NOTICES.md")
    shutil.copytree(root / "packaging/licenses/qt", destination / "qt", dirs_exist_ok=True)
    for candidate in (Path(sys.base_prefix) / "LICENSE", Path(sys.base_prefix) / "LICENSE.txt",
                      Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
                      Path("/usr/share/licenses/python/LICENSE")):
        if candidate.is_file():
            shutil.copyfile(candidate, destination / "Python-LICENSE.txt")
            break
    (destination / "dependencies.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return inventory


def build(root: Path, output: Path, work: Path, *, dry_run: bool = False,
          target: str | None = None, allow_wine: bool = False) -> dict:
    root = validate_root(root)
    host = native_platform()
    if target and target != host:
        raise ValueError("Cross-OS packaging is unsupported; build on a native target OS.")
    evidence = runtime_evidence()
    if evidence['wine'] and not allow_wine:
        raise ValueError('Wine is supplementary only; pass --allow-wine to build a labelled preview.')
    output, work = output.resolve(), work.resolve()
    # PyInstaller --noconfirm may replace its own APP_NAME output; it must never
    # point at a user's translation project or source directory.
    for path in (output, work):
        if path == root or root.is_relative_to(path):
            raise ValueError("Output/work directory must not contain the source repository.")
        if any((ancestor / "project.json").is_file() or (ancestor / "About/About.xml").is_file()
               for ancestor in (path, *path.parents)):
            raise ValueError("Output/work directory must not be inside a translation workspace or MOD.")
    bundle = output / APP_NAME
    if bundle.exists():
        validate_bundle(bundle)
        marker = bundle / "release-manifest.json"
        if any(bundle.iterdir()) and (not marker.is_file() or json.loads(marker.read_text(encoding="utf-8"))
                                     .get("application") != "rimworld-translation-editor"):
            raise ValueError("Existing output is not a known editor build; refusing to replace its files.")
    command = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
               "--distpath", str(output), "--workpath", str(work), str(root / "packaging/portable.spec")]
    plan = {"root": str(root), "platform": host, "version": __version__, "command": command,
            **evidence}
    if dry_run:
        return plan
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, cwd=root, check=True,
                   env=dict(os.environ, RIMWORLD_EDITOR_BUILD_ROOT=str(root),
                            PYINSTALLER_CONFIG_DIR=str(work / "pyinstaller-cache")))
    (bundle / "release-manifest.json").write_text(
        json.dumps({"application": "rimworld-translation-editor", "status": "built-not-verified"}),
        encoding="utf-8",
    )
    validate_bundle(bundle)
    inventory = collect_licenses(bundle, root)
    shutil.copyfile(root / "packaging/PORTABLE_README.txt", bundle / "README.txt")
    shutil.copyfile(root / "docs/DISTRIBUTION.md", bundle / "DISTRIBUTION.md")
    shutil.copyfile(root / "CHANGELOG.md", bundle / "CHANGELOG.md")
    for name in ('README.md','README.ja.md'):
        shutil.copyfile(root/name,bundle/name)
    guide_folder = bundle/'docs'
    guide_folder.mkdir(exist_ok=True)
    for name in ('DISTRIBUTION.md','GETTING_STARTED.md','GETTING_STARTED.ja.md'):
        shutil.copyfile(root/'docs'/name,guide_folder/name)
    for relative in ('packaging/THIRD_PARTY_NOTICES.md','rimworld_translator/assets/flags/LICENSE',
                     '.github/ISSUE_TEMPLATE/bug_report.yml','.github/ISSUE_TEMPLATE/feature_request.yml'):
        target = bundle/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/relative,target)
    executable = bundle / (APP_NAME + (".exe" if host == "windows" else ""))
    self_test = work / "binary-self-test.json"
    subprocess.run([str(executable), "--self-test", "--report", str(self_test)],
                   cwd=work, check=True, timeout=60)
    diagnostic = json.loads(self_test.read_text(encoding="utf-8"))
    if not diagnostic.get("frozen") or not diagnostic.get("ok"):
        raise ValueError("The portable executable failed its independent runtime self-test.")
    architecture = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "arm64"}.get(
        platform.machine().lower(), platform.machine().lower())
    manifest = {**plan, "application": "rimworld-translation-editor",
                "host": platform.platform(), "architecture": architecture,
                "python": platform.python_version(), "libc": platform.libc_ver(),
                "dependencies": inventory, "self_test": diagnostic,
                "executable_sha256": sha256_file(executable),
                "native_windows_verified": False,
                "native_windows_client_verified": False,
                "gui_verified": False, "validation_scope": "runtime-self-test"}
    # Do not distribute local build paths or command lines in the archive.
    public_manifest = {key: value for key, value in manifest.items() if key not in ("root", "command")}
    (bundle / "release-manifest.json").write_text(
        json.dumps(public_manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    archive = create_archive(bundle, output, host, architecture, wine_preview=evidence['wine'])
    checksum = sha256_file(archive)
    (output / f"{archive.name}.sha256").write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    result = {**public_manifest, "archive": str(archive), "sha256": checksum,
              "bundle": str(bundle), "executable": str(executable)}
    (output / "build-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def finalize(output: Path, gui_reports: list[Path], *, allow_wine: bool = False) -> dict:
    """Attach matching 100/200% GUI evidence and repack the verified bundle."""
    output = output.resolve()
    bundle = output / APP_NAME
    validate_bundle(bundle)
    manifest = json.loads((bundle / 'release-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('application') != 'rimworld-translation-editor' or manifest.get('version') != __version__:
        raise ValueError('Only the current editor build can be finalized.')
    host = manifest['platform']
    if host not in ('windows', 'linux'):
        raise ValueError('Unsupported release platform.')
    wine = bool(manifest.get('wine'))
    if wine and (host != 'windows' or not allow_wine):
        raise ValueError('Wine cannot finalize a native release; --allow-wine labels a supplementary preview.')
    if not all(manifest.get('self_test', {}).get(key) for key in ('ok', 'frozen')):
        raise ValueError('The frozen runtime self-test must pass before GUI validation.')
    executable = bundle / (APP_NAME + ('.exe' if host == 'windows' else ''))
    checksum = sha256_file(executable)
    verified = []
    for path in gui_reports:
        gui = json.loads(path.read_text(encoding='utf-8'))
        if gui.get('executable_sha256') != checksum:
            raise ValueError('GUI evidence belongs to a different executable.')
        if gui.get('version') != __version__ or not gui.get('frozen'):
            raise ValueError('GUI evidence must use the current frozen executable.')
        windows = gui.get('os') == 'win32' and gui.get('qt_backend') == 'windows'
        linux = str(gui.get('os', '')).startswith('linux') and gui.get('qt_backend') in ('xcb', 'wayland')
        if wine:
            valid_runtime = windows and gui.get('wine') is True and gui.get('native') is False
        else:
            valid_runtime = ((host == 'windows' and windows) or (host == 'linux' and linux)) and gui.get('native') is True and not gui.get('wine')
        if not valid_runtime:
            raise ValueError('GUI runtime must match native OS evidence, or an explicit Wine preview.')
        required = ('ok', 'save_verified', 'export_verified', 'history_verified',
                    'compact_save_shortcut_verified', 'keyboard_tab_moves_focus', 'initial_window_fits_screen')
        if not all(gui.get(key) is True for key in required) or gui.get('issues'):
            raise ValueError('GUI interaction, geometry and history verification must all pass.')
        verified.append((path, gui))
    if {gui.get('scale_factor') for _, gui in verified} != {'1', '2'} or len(verified) != 2:
        raise ValueError('Exactly one matching 100% and 200% GUI report is required.')
    summaries = []
    for path, gui in verified:
        destination = bundle / 'verification' / f"scale-{gui['scale_factor']}"
        destination.mkdir(parents=True, exist_ok=True)
        # Reports distributed with binaries omit local build paths.
        safe = {key: value for key, value in gui.items() if key not in ('host', 'executable')}
        for screenshot in gui.get('screenshots', []):
            name = screenshot['file']
            if Path(name).name != name:
                raise ValueError('Screenshot must be a file beside its GUI report.')
            shutil.copyfile(path.parent / name, destination / name)
        (destination / 'gui-report.json').write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding='utf-8')
        summaries.append({'scale_factor': gui['scale_factor'], 'report': (destination / 'gui-report.json').relative_to(bundle).as_posix(),
                          'native': gui['native'], 'wine': wine, 'executable_sha256': checksum})
    manifest.update(native_windows_verified=host == 'windows' and not wine, gui_verified=not wine, native_gui=not wine,
                    native_windows_client_verified=host == 'windows' and not wine and all(gui.get('native_windows_client_gui') is True for _, gui in verified),
                    supplementary_gui_verified=wine, validation_scope='wine-supplementary' if wine else 'native-gui',
                    executable_sha256=checksum, gui_verification=summaries)
    (bundle / 'release-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    archive = create_archive(bundle, output, host, manifest['architecture'], wine_preview=wine)
    archive_checksum = sha256_file(archive)
    (output / f'{archive.name}.sha256').write_text(f'{archive_checksum}  {archive.name}\n', encoding='utf-8')
    result = {**manifest, 'archive': str(archive), 'sha256': archive_checksum,
              'bundle': str(bundle), 'executable': str(executable)}
    (output / 'build-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build/portable")
    parser.add_argument("--target", choices=("linux", "windows"), help="Must match the native host OS")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument('--allow-wine', action='store_true', help='Supplementary Windows Wine preview; never native Windows verification')
    parser.add_argument('--finalize', type=Path, nargs='+', metavar='GUI_REPORT', help='Repack after both matching 100/200%% binary GUI reports pass')
    options = parser.parse_args(argv)
    try:
        if options.finalize:
            result = finalize(options.output, options.finalize, allow_wine=options.allow_wine)
        else:
            result = build(options.root, options.output, options.work_dir,
                           dry_run=options.dry_run, target=options.target, allow_wine=options.allow_wine)
    except (ValueError, OSError, subprocess.SubprocessError, metadata.PackageNotFoundError) as exc:
        parser.exit(1, f"Portable build failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
