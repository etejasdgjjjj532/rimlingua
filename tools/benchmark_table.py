"""Open/filter/sort timing of the main table with a synthetic project (no game data)."""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entries', type=int, default=50000)
    args = parser.parse_args()
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from rimworld_translator.core import Entry, Project, Scan
    from rimworld_translator.gui import Window
    app = QApplication([])
    timings = {}

    def measure(name, operation):
        start = time.perf_counter()
        result = operation()
        app.processEvents()
        timings[name] = round(time.perf_counter() - start, 3)
        return result

    with tempfile.TemporaryDirectory(prefix='rimworld-table-') as temporary:
        base = Path(temporary)
        (base / 'source').mkdir()
        entries = [Entry(f'DefInjected:ThingDef:Item{i}.label', 'DefInjected', 'ThingDef', f'Item{i}.label',
                         f'Sample source item {i}', f'Defs/file{i % 40}.xml') for i in range(args.entries)]
        project = Project.create(base / 'source', Scan(entries=entries), ['Japanese'])
        path = base / 'work/project.json'
        project.save(path)
        window = Window(settings_path=base / 'settings.json')
        try:
            measure('open_project', lambda: (window.load_project(path), window.show()))

            def type_text(text):
                # Character by character like a person, then until the table reflects the whole text.
                if not text:
                    window.search.clear()
                for end in range(1, len(text) + 1):
                    window.search.setText(text[:end])
                    app.processEvents()
                deadline = time.perf_counter() + 60
                while window.proxy.query != text.casefold() and time.perf_counter() < deadline:
                    app.processEvents()
                    time.sleep(0.01)
            measure('type_rare_word', lambda: type_text(f'Item{args.entries - 1}'))
            timings['rare_rows'] = window.proxy.rowCount()
            measure('clear_search', lambda: type_text(''))
            measure('type_common_word', lambda: type_text('item 1'))
            timings['common_rows'] = window.proxy.rowCount()
            measure('clear_search_2', lambda: type_text(''))
            measure('navigate_last', lambda: window.navigate_entry(entries[-1].id))
            timings['navigate_ok'] = window.current is not None and window.current.id == entries[-1].id
        finally:
            window.dirty = False
            window.close()
    print(json.dumps({'entries': args.entries, 'timings': timings}, indent=1))


if __name__ == '__main__':
    main()
