# Native PyInstaller onedir bundle. Data: owned flag assets and the RimWorld field-name table (names only).
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(os.environ.get("RIMWORLD_EDITOR_BUILD_ROOT", SPECPATH)).resolve()
if root.name == "packaging":
    root = root.parent

analysis = Analysis(
    [str(root / "packaging/launcher.py")],
    pathex=[str(root)],
    binaries=[],
    datas=collect_data_files("rimworld_translator", includes=["assets/flags/*.svg", "assets/flags/LICENSE", "assets/field_contracts.json"]),
    hiddenimports=["lxml.etree", "dnfile", "polib", "tools.verify_native_gui"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
              "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PyQt6", "PyQt5", "tkinter", "matplotlib", "numpy"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True,
    name="RimWorldTranslationEditor", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
    disable_windowed_traceback=False,
)
collection = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False,
                     name="RimWorldTranslationEditor")
