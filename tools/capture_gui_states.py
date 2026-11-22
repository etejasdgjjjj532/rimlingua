"""Capture the editor on a real display in both themes and measure what a reviewer would look for.

    python tools/run_tests.py --script tools/capture_gui_states.py --project <project.json> --output <dir>

Run through the isolating runner on a desktop session (not offscreen). The project is opened from a
copy, so the given project and its exported MOD are never written. Writes PNGs and report.json:
clipped column headings, dark surfaces in the light theme, whether the list and editor fit the
window, chip/dropdown synchronisation, the clear-filter button, focus rings and edit latency.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--size', default='', help='WIDTHxHEIGHT to request; a tiling compositor decides the real size')
    parser.add_argument('--fullscreen', action='store_true', help='ask for the whole screen instead of a tile')
    args = parser.parse_args()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QHeaderView
    from rimworld_translator.gui import Window

    app = QApplication.instance() or QApplication([])
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    report = {'qt_platform': app.platformName(), 'screen': [app.primaryScreen().size().width(), app.primaryScreen().size().height()],
              'device_pixel_ratio': app.primaryScreen().devicePixelRatio(), 'font': app.font().family(), 'themes': {}}

    def settle(times=12):
        for _ in range(times):
            app.processEvents()
            time.sleep(0.03)

    with tempfile.TemporaryDirectory(prefix='rimworld-gui-states-') as folder:
        work = Path(folder) / 'workspace'
        work.mkdir()
        shutil.copy2(args.project, work / 'project.json')
        for mode in ('light', 'dark'):
            window = Window(settings_path=Path(folder) / f'settings-{mode}.json')
            window.error = lambda text: report.setdefault('errors', []).append(str(text))
            window.set_theme_mode(mode, persist=False)
            if args.size:
                window.resize(*map(int, args.size.split('x')))
            window.showFullScreen() if args.fullscreen else window.show()
            settle(30)
            data = {'screenshots': []}

            def shot(name, widget=None):
                settle()
                path = out / f'{mode}-{name}.png'
                image = (widget or window).grab()
                image.save(str(path))
                data['screenshots'].append(path.name)
                return image.toImage()

            def dark_share(image):
                """Share of sampled pixels darker than a mid grey (a dark panel inside a light window)."""
                dark = total = 0
                for x in range(0, image.width(), 8):
                    for y in range(0, image.height(), 8):
                        total += 1
                        dark += image.pixelColor(x, y).lightness() < 70
                return round(dark / max(total, 1), 4)

            shot('01-initial')
            started = time.perf_counter()
            window.load_project(work / 'project.json')
            settle()
            data['load_seconds'] = round(time.perf_counter() - started, 2)
            data['entries'] = len(window.model.entries)
            data['window'] = [window.width(), window.height()]
            image = shot('02-editor')
            data['dark_pixel_share_editor'] = dark_share(image)
            # Column headings: text wider than its section is drawn clipped or elided.
            header = window.table.horizontalHeader()
            metrics = QFontMetrics(header.font())
            clipped = []
            for column in range(window.model.columnCount()):
                text = str(window.model.headerData(column, Qt.Horizontal))
                if not header.isSectionHidden(column) and metrics.horizontalAdvance(text) + 12 > header.sectionSize(column):
                    clipped.append({'column': column, 'text': text, 'needs': metrics.horizontalAdvance(text) + 12,
                                    'has': header.sectionSize(column)})
            data['clipped_headers'] = clipped
            # Do the list and the editor both sit inside the window, each with usable height?
            def box(widget):
                top = widget.mapTo(window, widget.rect().topLeft()).y()
                return {'top': top, 'bottom': top + widget.height(), 'height': widget.height(), 'visible': widget.isVisible()}
            data['table'] = box(window.table)
            data['japanese_editor'] = box(window.japanese)
            data['english_view'] = box(window.english) if hasattr(window, 'english') else None
            row_height = window.table.verticalHeader().defaultSectionSize() or 1
            data['visible_rows'] = max(0, (window.table.viewport().height()) // row_height)
            data['fits_window'] = (data['japanese_editor']['bottom'] <= window.height()
                                   and data['table']['bottom'] <= window.height())
            # Chips and the dropdown describe the same filter.
            sync = {}
            data['clear_button_before_filter'] = window.clear_filters_button.isVisible()
            for key, chip in window.status_chips.items():
                chip.click()
                settle(3)
                sync['chip:' + (key or 'all')] = window.status_filter.currentData() == key and chip.isChecked()
            for index in range(window.status_filter.count()):
                window.status_filter.setCurrentIndex(index)
                settle(3)
                key = window.status_filter.currentData()
                chip = window.status_chips.get(key)
                sync['dropdown:' + (key or 'all')] = bool(chip and chip.isChecked()
                                                         and sum(c.isChecked() for c in window.status_chips.values()) == 1)
            data['chip_dropdown_sync'] = sync
            window.status_chips['untranslated'].click()
            settle()
            data['clear_button_while_filtered'] = window.clear_filters_button.isVisible()
            data['filtered_rows'] = window.proxy.rowCount()
            shot('03-filtered-untranslated')
            window.clear_filters_button.click()
            settle()
            data['clear_button_after_clear'] = window.clear_filters_button.isVisible()
            window.search.setText('label')
            settle()
            data['clear_button_while_searching'] = window.clear_filters_button.isVisible()
            window.clear_filters()
            settle()
            # Keyboard focus: tab through the controls and photograph three stops.
            window.search.setFocus(Qt.TabFocusReason)
            settle(3)
            stops = []
            for step in range(8):
                focused = app.focusWidget()
                stops.append(type(focused).__name__ + ':' + (focused.objectName() or focused.accessibleName() or '') if focused else None)
                if step in (0, 2, 4):
                    shot(f'04-focus-ring-{step}')
                QTest.keyClick(app.focusWidget() or window, Qt.Key_Tab)
                settle(2)
            data['tab_stops'] = stops
            # Scrolling and typing with the whole project loaded.
            if window.proxy.rowCount():
                window.table.setCurrentIndex(window.proxy.index(0, 0))
                settle(3)
                bar = window.table.verticalScrollBar()
                started = time.perf_counter()
                for value in range(0, bar.maximum() + 1, max(1, bar.maximum() // 60)):
                    bar.setValue(value)
                    app.processEvents()
                data['scroll_60_steps_ms'] = round((time.perf_counter() - started) * 1000)
                bar.setValue(0)
                window.table.setCurrentIndex(window.proxy.index(min(3, window.proxy.rowCount() - 1), 0))
                settle(3)
                window.japanese.setFocus()
                before = window.japanese.toPlainText()
                timings = []
                for character in 'テスト入力の速さ':
                    started = time.perf_counter()
                    window.japanese.insertPlainText(character)
                    app.processEvents()
                    timings.append((time.perf_counter() - started) * 1000)
                data['keystroke_ms_max'] = round(max(timings), 1)
                data['keystroke_ms_median'] = round(sorted(timings)[len(timings) // 2], 1)
                window.japanese.setPlainText(before)
                settle(3)
            for index, name in ((1, '05-review-tab'), (2, '06-progress-tab'), (3, '07-export-tab')):
                window.workspace_tabs.setCurrentIndex(index)
                settle()
                image = shot(name)
                data['dark_pixel_share_' + name[3:]] = dark_share(image)
            window.workspace_tabs.setCurrentIndex(0)
            settle()
            window.set_focus_mode(True)
            image = shot('08-focus-mode')
            data['dark_pixel_share_focus-mode'] = dark_share(image)
            data['focus_mode_editor'] = box(window.japanese)
            window.set_focus_mode(False)
            report['themes'][mode] = data
            window.dirty = False
            window.autosave.stop()
            window.close()
            settle()
    (out / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
