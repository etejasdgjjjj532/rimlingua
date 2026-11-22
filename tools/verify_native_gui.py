"""Check native/offscreen GUI geometry, accessibility, editing and DPI captures.

Screenshots use a generated demonstration project and contain no game/MOD assets.
Native Windows is reported only by Python/EXE running on Windows with the windows
Qt platform plugin. Offscreen and Wine results are never native Windows evidence.
"""
import argparse
import json
import inspect
import os
from pathlib import Path
import platform
import sys
import tempfile
import xml.etree.ElementTree as ET
import hashlib

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run_smoke(output: Path, *, require_native: bool = False, require_windows_client: bool = False) -> dict:
    from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
    from PySide6.QtGui import QAccessible
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from rimworld_translator.core import Entry, Project
    from rimworld_translator.gui import Window
    from rimworld_translator.version import __version__
    from rimworld_translator.runtime import runtime_evidence

    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    font = app.font()
    font.setPointSize(11)
    app.setFont(font)
    backend = app.platformName()
    evidence = runtime_evidence(backend)
    native = evidence['native_gui']
    report = {"version": __version__, "host": platform.platform(), "os": sys.platform,
              "qt_backend": backend, "native": native, "frozen": bool(getattr(sys, "frozen", False)),
              "scale_factor": os.environ.get("QT_SCALE_FACTOR", "1"),
              "screenshots": [], "accessibility": {}, "issues": [], **evidence}
    report['executable_sha256'] = None
    if report['frozen']:
        with open(sys.executable, 'rb') as stream:
            report['executable_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    if require_native and not native:
        report["issues"].append(f"A native GUI is required; current Qt platform is {backend}.")
    if require_windows_client and not evidence['native_windows_client_gui']:
        report['issues'].append('A native Windows 10/11 client GUI is required; Server, Wine and offscreen do not satisfy this check.')
    with tempfile.TemporaryDirectory(prefix="rimworld-native-gui-") as folder:
        source = Path(folder) / "source"
        source.mkdir()
        entries = [
            Entry("DefInjected:ThingDef:Demo.label", "DefInjected", "ThingDef", "Demo.label",
                  "Demonstration item", "Defs/Demo.xml", "確認用の翻訳"),
            Entry("Keyed:Keyed:DemoTip", "Keyed", "Keyed", "DemoTip",
                  "A demonstration with {0} settings.", "Languages/English/Keyed/Demo.xml"),
        ]
        project = Project(str(source), "Demonstration / 動作確認", "local.translation.demo",
                          "demo.original", ["1.6"], entries, [],
                          languages=["Japanese", "French", "German"])
        path = Path(folder) / "workspace/project.json"
        project.save(path)
        if "settings_path" in inspect.signature(Window).parameters:
            window = Window(settings_path=Path(folder) / "ui-settings.json")
        else:
            # Older sources had no persisted preferences. Current sources must
            # use disposable settings so smoke tests do not touch user choices.
            window = Window()
        # Unattended validation records normal error-dialog content in the
        # report instead of waiting forever for a person to dismiss a modal.
        window.error = lambda message: report["issues"].append(str(message))
        try:
            window.load_project(path)
            window.show()
            window.activateWindow()
            app.processEvents()
            QTest.qWait(120)
            report['keyboard_window_active'] = QTest.qWaitForWindowActive(window, 2000)
            if not report['keyboard_window_active']:
                report['issues'].append('Keyboard verification requires the GUI window to have focus; another application may be active.')
            window.table.setCurrentIndex(window.proxy.index(0, 0))
            app.processEvents()
            if window.japanese.toPlainText() != "確認用の翻訳":
                report["issues"].append("Selecting a translated entry did not show its translation.")
            edited_text = "保存と書き出しを確認した翻訳"
            window.japanese.setPlainText(edited_text)
            app.processEvents()
            report["save_verified"] = bool(window.save()
                and Project.load(path).entries[0].japanese == edited_text)
            if not report["save_verified"]:
                report["issues"].append("A GUI edit did not survive saving and reopening the project.")
            report["export_verified"] = False
            if window.generate():
                exported = path.parent / "mod/Languages/Japanese/DefInjected/ThingDef/Translations.xml"
                if exported.is_file():
                    report["export_verified"] = ET.parse(exported).getroot().findtext("Demo.label") == edited_text
            if not report["export_verified"]:
                report["issues"].append("The edited translation was not present in exported game XML.")
            report["device_pixel_ratio"] = window.devicePixelRatioF()
            screen = window.screen().availableGeometry()
            report["screen_logical_size"] = [screen.width(), screen.height()]
            report['initial_window_fits_screen'] = window.width()<=screen.width() and window.height()<=screen.height()
            for label, widget in (("search", window.search), ("source", window.english),
                                  ("translation", window.japanese), ("export", window.export_button)):
                interface = QAccessible.queryAccessibleInterface(widget)
                valid = interface is not None and interface.isValid()
                name = interface.text(QAccessible.Name) if valid else ""
                report["accessibility"][label] = {
                    "valid": valid, "name": name,
                    "keyboard_focus": widget.focusPolicy() != Qt.NoFocus,
                }
                if not valid or not name:
                    report["issues"].append(f"Missing accessible name/interface for {label}.")
            window.search.setFocus(Qt.OtherFocusReason)
            app.processEvents()
            moved = window.focusNextChild()
            app.processEvents()
            report["keyboard_tab_moves_focus"] = bool(moved and window.focusWidget() is not None
                                                       and window.focusWidget() is not window.search)
            if not report["keyboard_tab_moves_focus"]:
                report["issues"].append("Tab navigation from the search field did not move focus.")
            for width, height in ((1240, 730), (960, 660), (max(480,min(660,screen.width()-20)),max(280,min(350,screen.height()-40)))):
                window.resize(width, height)
                app.processEvents()
                if window.width() < width or window.height() < height:
                    # The OS clamped the window to a screen smaller than this size (e.g. a small CI display at
                    # 200%), so the size was never applied and says nothing about the layout.
                    report.setdefault('skipped_sizes', []).append(
                        f'{width}x{height} was clamped to {window.width()}x{window.height()} by the screen')
                    continue
                QTest.qWait(80)
                controls = {}
                for name in ("table", "search", "english", "japanese", "save_button",
                             "export_button", "language_selector"):
                    widget = getattr(window, name)
                    if name=='save_button' and not widget.isVisible():
                        # Compact layouts expose Save through the menu/Ctrl+S.
                        window.japanese.setPlainText(edited_text+' compact')
                        QTest.keyClick(window,Qt.Key_S,Qt.ControlModifier)
                        app.processEvents()
                        if Project.load(path).entries[0].japanese!=edited_text+' compact':
                            report['issues'].append('Compact Ctrl+S did not save the current translation.')
                        report['compact_save_shortcut_verified'] = Project.load(path).entries[0].japanese==edited_text+' compact'
                        continue
                    if hasattr(window,'editor_scroll'):
                        window.editor_scroll.ensureWidgetVisible(widget)
                        app.processEvents()
                        # A table can be larger than the viewport. Qt's default
                        # margins cannot expose the whole widget in that case;
                        # explicitly expose the point whose reachability we test.
                        anchor = widget.mapTo(window.editor_scroll.widget(), widget.rect().center())
                        window.editor_scroll.ensureVisible(anchor.x(), anchor.y(), 1, 1)
                        app.processEvents()
                    point = widget.mapTo(window, QPoint(0, 0))
                    rectangle = QRect(point, widget.size())
                    controls[name] = [rectangle.x(), rectangle.y(), rectangle.width(), rectangle.height()]
                    if hasattr(window,'editor_scroll'):
                        viewport = window.editor_scroll.viewport()
                        center = widget.mapTo(viewport,widget.rect().center())
                        if not viewport.rect().contains(center):
                            report['issues'].append(f'{name} cannot be reached in the scroll viewport at {width}x{height}.')
                    if not widget.isVisible() or rectangle.width() <= 0 or rectangle.height() <= 0:
                        report["issues"].append(f"{name} is not visible at {width}x{height}.")
                    elif width>680 and not window.rect().adjusted(-1, -1, 1, 1).contains(rectangle):
                        report["issues"].append(f"{name} falls outside the window at {width}x{height}.")
                # Exercise an actual cell at each size, not just the table's
                # bounding box. The outer scroll area must expose the click.
                index = window.proxy.index(0, 0)
                window.table.scrollTo(index)
                app.processEvents()
                cell = window.table.visualRect(index).center()
                anchor = window.table.viewport().mapTo(window.editor_scroll.widget(), cell)
                window.editor_scroll.ensureVisible(anchor.x(), anchor.y(), 1, 1)
                app.processEvents()
                click = window.table.viewport().mapTo(window.editor_scroll.viewport(), cell)
                reachable = window.editor_scroll.viewport().rect().contains(click)
                window.table.clearSelection()
                if reachable:
                    QTest.mouseClick(window.table.viewport(), Qt.LeftButton, pos=cell)
                    app.processEvents()
                selected = bool(reachable and window.table.selectionModel().isSelected(index)
                                and window.current is not None
                                and window.current.id == entries[0].id)
                if not selected:
                    report['issues'].append(f'Table cell cannot be selected at {width}x{height}.')
                image = window.grab()
                filename = f"editor-{width}x{height}.png"
                if not image.save(str(output / filename)):
                    report["issues"].append(f"Screenshot could not be saved: {filename}")
                report["screenshots"].append({"file": filename,
                    "requested_logical_size": [width, height],
                    "actual_logical_size": [window.width(), window.height()],
                    "pixel_width": image.width(), "pixel_height": image.height(), "controls": controls,
                    "table_selection_verified": selected,
                    "fits_screen": window.width() <= screen.width() and window.height() <= screen.height()})
            from rimworld_translator.history import list_snapshots
            records = list_snapshots(path)
            report['history_verified'] = bool(records)
            report['history_backends'] = sorted({record.backend for record in records})
            if not records:
                report['issues'].append('GUI saves did not create a usable local history snapshot.')
        finally:
            window.dirty = False
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
    report["ok"] = not report["issues"]
    (output / "gui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/gui-native"))
    parser.add_argument("--require-native", action="store_true")
    parser.add_argument('--require-windows-client',action='store_true')
    options = parser.parse_args(argv)
    result = run_smoke(options.output, require_native=options.require_native, require_windows_client=options.require_windows_client)
    if sys.stdout is not None:
        # Frozen Windows apps can receive a legacy-encoded redirected stream.
        # Keep stdout portable; the report file still contains literal UTF-8.
        print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
