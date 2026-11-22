"""Read-only RimWorld installation discovery on Windows and Linux."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
from typing import Iterable


@dataclass(frozen=True)
class GameInstallation:
    root: Path
    mods: Path
    workshop: Path | None
    version: str
    executable: Path | None
    platform: str = sys.platform
    distribution: str = "Custom"


def _vdf(path: Path) -> dict:
    """Read Steam's old or new KeyValues files without a third-party parser."""
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            return {}
        content = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return {}
    tokens = re.findall(r'//[^\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+', content)
    tokens = [token for token in tokens if not token.startswith("//")]
    index = 0

    def unquote(token: str) -> str:
        return re.sub(r'\\([\\"])', r'\1', token[1:-1]) if token.startswith('"') else token

    def parse(depth: int = 0) -> dict:
        nonlocal index
        if depth > 20:
            raise ValueError("VDF nesting is too deep")
        result = {}
        while index < len(tokens):
            key = tokens[index]
            index += 1
            if key == "}":
                return result
            if key == "{" or index >= len(tokens):
                raise ValueError("Malformed VDF")
            value = tokens[index]
            index += 1
            if value == "{":
                value = parse(depth + 1)
            elif value == "}":
                raise ValueError("Missing VDF value")
            else:
                value = unquote(value)
            result[unquote(key).casefold()] = value
        if depth:
            raise ValueError("Unclosed VDF block")
        return result

    try:
        return parse()
    except ValueError:
        return {}


def _windows_steam_roots() -> list[Path]:
    """Query installed Steam registry keys; never create or modify a key."""
    try:
        import winreg
    except ImportError:
        return []
    roots = []
    for hive, key, fields in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", ("SteamPath", "SteamExe")),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam", ("InstallPath",)),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam", ("InstallPath",)),
    ):
        try:
            with winreg.OpenKey(hive, key, 0, winreg.KEY_READ) as handle:
                for field in fields:
                    try:
                        value, _ = winreg.QueryValueEx(handle, field)
                        if isinstance(value, str) and value:
                            path = Path(value)
                            roots.append(path.parent if field == "SteamExe" else path)
                    except OSError:
                        pass
        except OSError:
            pass
    return roots


def _steam_roots(platform: str, home: Path) -> list[Path]:
    if platform.startswith("win"):
        roots = _windows_steam_roots()
        for variable in ("ProgramFiles(x86)", "ProgramFiles", "PROGRAMFILES(X86)", "PROGRAMFILES"):
            if os.environ.get(variable):
                roots.append(Path(os.environ[variable]) / "Steam")
        return roots
    return [
        home / ".local/share/Steam", home / ".steam/steam", home / ".steam/root",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ]


def _libraries(root: Path) -> list[Path]:
    if root.name.casefold() == "steamapps":
        root = root.parent
    paths = [root]
    folders = _vdf(root / "steamapps/libraryfolders.vdf").get("libraryfolders", {})
    if isinstance(folders, dict):
        for key, entry in folders.items():
            if not key.isdigit():
                continue
            value = entry.get("path") if isinstance(entry, dict) else entry
            if isinstance(value, str) and value:
                paths.append(Path(value))
    return paths


def _installation(root: Path, platform: str, workshop: Path | None = None) -> GameInstallation | None:
    if root.is_file():
        root = root.parent
    from .game_library import child, descend
    root = root.expanduser().resolve()
    core = descend(root, "Data", "Core")
    if core is None or not core.is_dir():
        return None
    if workshop is None and root.parent.name.casefold() == "common" and root.parent.parent.name.casefold() == "steamapps":
        workshop = root.parent.parent / "workshop/content/294100"
    names = ("RimWorldWin64.exe", "RimWorldWin.exe") if platform.startswith("win") else (
        "RimWorldLinux", "RimWorldLinux.x86_64", "RimWorldLinux.x86",
    )
    executable = next((root / name for name in names if (root / name).is_file()), None)
    version_file = child(root, "Version.txt")
    if executable is None and (version_file is None or not version_file.is_file()):
        return None
    version = ""
    try:
        if version_file is not None and version_file.stat().st_size < 1024 * 1024:
            match = re.search(r"\b\d+\.\d+(?:\.\d+)*\b", version_file.read_text(encoding="utf-8-sig", errors="replace"))
            if match:
                version = match.group()
    except OSError:
        pass
    return GameInstallation(root, root / "Mods", workshop.resolve() if workshop else None,
                            version, executable, platform, "Steam" if workshop else "Custom")


def discover_installations(
    custom_paths: Iterable[Path | str] = (), *, platform: str | None = None,
    home: Path | str | None = None, steam_roots: Iterable[Path | str] = (),
) -> list[GameInstallation]:
    """Discover all Steam libraries, plus explicitly supplied game folders/binaries.

    ``home`` and ``steam_roots`` can be supplied for portable installations and tests.
    A missing version is represented by an empty string; discovery never writes.
    """
    platform = platform or sys.platform
    home = Path(home).expanduser() if home is not None else Path.home()
    found: dict[str, GameInstallation] = {}
    seen_libraries = set()

    def identity(path: Path) -> str:
        text = str(path.resolve())
        return text.casefold() if platform.startswith("win") else text

    for root in [*(Path(path).expanduser() for path in steam_roots), *_steam_roots(platform, home)]:
        for library in _libraries(root):
            library = library.expanduser().resolve()
            key = identity(library)
            if key in seen_libraries:
                continue
            seen_libraries.add(key)
            appstate = _vdf(library / "steamapps/appmanifest_294100.acf").get("appstate", {})
            directory = appstate.get("installdir", "RimWorld") if isinstance(appstate, dict) else "RimWorld"
            if not isinstance(directory, str) or not directory or directory in {".", ".."} or any(c in directory for c in '/\\:'):
                directory = "RimWorld"
            item = _installation(library / "steamapps/common" / directory, platform,
                                 library / "steamapps/workshop/content/294100")
            if item:
                found[identity(item.root)] = item
    for path in custom_paths:
        item = _installation(Path(path), platform)
        if item:
            found.setdefault(identity(item.root), item)
    return list(found.values())


def user_data_directory(platform=None,home=None) -> Path:
    """Return the usual game profile path for read-only diagnostics."""
    platform,home = platform or sys.platform,Path(home or Path.home())
    if platform=='win32':
        return home/'AppData/LocalLow/Ludeon Studios/RimWorld by Ludeon Studios'
    return home/'.config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios'


def app_cache_directory(platform=None, home=None, environ=None, override='') -> Path:
    """Where this editor keeps data it can rebuild, such as the field table read from the user's own game."""
    if override:
        return Path(override).expanduser()
    platform, home, environ = platform or sys.platform, Path(home or Path.home()), os.environ if environ is None else environ
    if platform == 'win32':
        return Path(environ.get('LOCALAPPDATA') or home / 'AppData/Local') / 'RimWorldTranslationEditor/cache'
    if platform == 'darwin':
        return home / 'Library/Caches/RimWorldTranslationEditor'
    return Path(environ.get('XDG_CACHE_HOME') or home / '.cache') / 'rimworld-translation-editor'


# Folders this editor creates inside its cache directory; nothing else there is ever removed.
# (The per-project schema cache lives in the project's own .cache folder, never here.)
CACHE_SUBFOLDERS = ('game-table',)
CACHE_MARKER = '.rimworld-translation-editor-cache'


def mark_cache_folder(folder: Path | str) -> None:
    """Record that this editor owns ``folder``, so clearing the cache may delete it later."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / CACHE_MARKER).write_text('Created by RimWorld Translation Editor; safe to delete.\n', encoding='utf-8')


def clear_app_cache_report(directory: Path | str) -> tuple[int, list[str]]:
    """Delete the marked cache folders inside ``directory``; returns (removed count, names skipped as not ours).

    The directory may be one the user chose, so only known subfolders that carry the ownership marker go, never
    the directory itself or anything else in it. Folders without the marker are left untouched and reported.
    Symbolic links are never followed or removed.
    """
    import shutil
    directory, removed, skipped = Path(directory).expanduser(), 0, []
    for name in CACHE_SUBFOLDERS:
        target = directory / name
        try:
            if target.is_symlink():
                skipped.append(name)
                continue
            if not target.is_dir():
                continue
            if not (target / CACHE_MARKER).is_file():
                skipped.append(name)
                continue
            shutil.rmtree(target)
            removed += 1
        except OSError:
            skipped.append(name)
    return removed, skipped


def clear_app_cache(directory: Path | str) -> int:
    """Like ``clear_app_cache_report`` but returns only how many folders were removed."""
    return clear_app_cache_report(directory)[0]


# The game's profile inside a Proton prefix, relative to a Steam library.
PROTON_PROFILE = ('steamapps/compatdata/294100/pfx/drive_c/users/steamuser/AppData/LocalLow/'
                  'Ludeon Studios/RimWorld by Ludeon Studios')


def steam_libraries(platform: str | None = None, home: Path | str | None = None,
                    steam_roots: Iterable[Path | str] = ()) -> list[Path]:
    """Every Steam library folder this user has, each once; nothing is created."""
    platform = platform or sys.platform
    home = Path(home).expanduser() if home is not None else Path.home()
    found, seen = [], set()
    for root in [*(Path(path).expanduser() for path in steam_roots), *_steam_roots(platform, home)]:
        for library in _libraries(root):
            key = os.path.normcase(str(library.expanduser().absolute()))
            if key not in seen:
                seen.add(key)
                found.append(library.expanduser())
    return found


def mods_config_candidates(override: str = '', *, platform: str | None = None, home: Path | str | None = None,
                           steam_roots: Iterable[Path | str] = ()) -> list[Path]:
    """Where ModsConfig.xml may be, most likely first. A user-set file or profile folder is the only candidate."""
    if override:
        path = Path(override).expanduser()
        return [path / 'Config/ModsConfig.xml' if path.is_dir() else path]
    platform = platform or sys.platform
    candidates = [user_data_directory(platform, home) / 'Config/ModsConfig.xml']
    if not platform.startswith('win'):
        # Steam Play keeps the Windows profile inside each library's prefix.
        candidates += [library / PROTON_PROFILE / 'Config/ModsConfig.xml'
                       for library in steam_libraries(platform, home, steam_roots)]
    return candidates


def find_mods_config(override: str = '', **kwargs) -> Path | None:
    """The first existing ModsConfig.xml; it is only ever read."""
    return next((path for path in mods_config_candidates(override, **kwargs) if path.is_file()), None)


@dataclass(frozen=True)
class ModRoots:
    """Folders that hold MODs, all read-only: prerequisites and source MODs are looked up here."""
    workshop: tuple[Path, ...]
    mods: tuple[Path, ...]
    external: tuple[Path, ...]

    def all(self) -> tuple[Path, ...]:
        return tuple(dict.fromkeys((*self.workshop, *self.mods, *self.external)))


def detected_workshop(games) -> list[Path]:
    return list(dict.fromkeys(g.workshop for g in games if g.workshop is not None and g.workshop.is_dir()))


def detected_mods(games) -> list[Path]:
    return list(dict.fromkeys(g.mods for g in games if g.mods.is_dir()))


def mod_roots(settings_data, games) -> ModRoots:
    """The user's folders where set; otherwise what discovery found, as before."""
    workshop = settings_data.get('workshop_folder', '')
    mods = settings_data.get('mods_folder', '')
    return ModRoots((Path(workshop).expanduser(),) if workshop else tuple(detected_workshop(games)),
                    (Path(mods).expanduser(),) if mods else tuple(detected_mods(games)),
                    tuple(Path(p).expanduser() for p in settings_data.get('external_mod_folders', []) if p))


def mod_folders(roots: Iterable[Path]) -> list[Path]:
    """MOD folders (those with About/About.xml) directly inside ``roots``, each once, in order."""
    found, seen = [], set()
    for root in roots:
        try:
            children = sorted(Path(root).iterdir()) if Path(root).is_dir() else []
        except OSError:
            continue
        for folder in children:
            try:
                if folder.name.startswith('.') or not folder.is_dir() or not (folder / 'About/About.xml').is_file():
                    continue
            except OSError:
                continue
            key = os.path.normcase(str(folder.absolute()))
            if key not in seen:
                seen.add(key)
                found.append(folder)
    return found


def is_mod_folder(folder: Path | str) -> bool:
    """True for a folder RimWorld could load as a MOD: About/About.xml, or Defs/Languages at the top or in a version folder."""
    from .game_library import child, descend
    folder = Path(folder)
    if not folder.is_dir():
        return False
    about = descend(folder, 'About', 'About.xml')
    if about is not None and about.is_file():
        return True
    try:
        layers = [folder, *(entry for entry in folder.iterdir() if entry.is_dir()
                            and (re.fullmatch(r'v?\d+\.\d+', entry.name) or entry.name.casefold() == 'common'))]
    except OSError:
        return False
    return any((found := child(layer, name)) is not None and found.is_dir()
               for layer in layers for name in ('Defs', 'Languages', 'Patches'))
