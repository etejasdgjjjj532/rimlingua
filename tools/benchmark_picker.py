"""Measure an actual Qt source picker with 1000 generated read-only inputs."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('artifacts/picker-performance.json'))
    args = parser.parse_args()
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtCore import Qt,QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QDialog,QLineEdit,QListWidget,QWidget
    from rimworld_translator.dialogs import select_workshop_mod
    from rimworld_translator.settings import SettingsStore
    app = QApplication([])
    report = {'source_count':1000,'qt_backend':app.platformName(),'synthetic_inputs':True,'heartbeat_ticks':0}
    with tempfile.TemporaryDirectory(prefix='rimworld-picker-benchmark-') as folder:
        root = Path(folder)
        for number in range(1000):
            about = root/'workshop'/str(3000000000+number)/'About/About.xml'
            about.parent.mkdir(parents=True)
            about.write_text(f'<ModMetaData><name>Source {number:04}</name><author>Author {number:04}</author><packageId>sample.mod{number}</packageId></ModMetaData>')
        parent = QWidget()
        parent.ui_language = 'en'
        parent.settings = SettingsStore(root/'settings.json')
        start = time.monotonic()
        gaps,last_tick = [],[start]
        def heartbeat():
            now = time.monotonic()
            gaps.append(now-last_tick[0])
            last_tick[0] = now
            report['heartbeat_ticks'] += 1
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(heartbeat)
        timer.start()
        def operate(dialog):
            report['initial_ready_seconds'] = round(time.monotonic()-start,4)
            dialog.show()
            listing = dialog.findChild(QListWidget)
            assert listing.count()==1000
            while not listing.item(999).text().startswith('Source 0999'):
                if time.monotonic()-start>30:
                    raise RuntimeError('Metadata indexing did not finish within 30 seconds')
                app.processEvents()
                QTest.qWait(1)
            report['indexed_seconds'] = round(time.monotonic()-start,4)
            search_start = time.monotonic()
            dialog.findChild(QLineEdit).setText('Author 0999')
            app.processEvents()
            visible = [listing.item(i) for i in range(listing.count()) if not listing.item(i).isHidden()]
            assert len(visible)==1 and visible[0].data(Qt.UserRole)==str(root/'workshop/3000000999')
            listing.setCurrentItem(visible[0])
            report['author_search_seconds'] = round(time.monotonic()-search_start,4)
            return QDialog.Accepted
        try:
            with patch.object(QDialog,'exec',new=operate):
                selected = select_workshop_mod(parent,root/'workshop')
            assert selected==root/'workshop/3000000999'
            assert report['heartbeat_ticks']>0
            report['max_event_loop_gap_seconds'] = round(max(gaps),4)
            report['ok'] = True
        finally:
            timer.stop()
            parent.close()
            app.processEvents()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
