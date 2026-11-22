"""Render a synthetic, copyright-free editing session and exit."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from rimworld_translator.core import Entry, Project
from rimworld_translator.gui import Window


def main():
    app = QApplication([])
    font = app.font()
    font.setPointSize(11)
    app.setFont(font)
    with tempfile.TemporaryDirectory(prefix='rimworld-gui-smoke-') as folder:
        root = Path(folder)
        source = root / 'source'
        source.mkdir()
        entries = [Entry('DefInjected:ThingDef:Demo.label', 'DefInjected', 'ThingDef', 'Demo.label', 'Demonstration item', 'Defs/Demo.xml', 'デモ用アイテム'), Entry('DefInjected:ThingDef:Demo.description', 'DefInjected', 'ThingDef', 'Demo.description', 'A demonstration with {0} adjustable settings.\nLong strings can be edited in the lower pane.', 'Defs/Demo.xml', '設定項目が {0} 個あるデモです。\n長文は下の欄で編集できます。', review=True), Entry('Keyed:Keyed:DemoTip', 'Keyed', 'Keyed', 'DemoTip', 'Select an entry to translate it.', 'Languages/English/Keyed/Demo.xml')]
        project = Project(str(source), '動作確認プロジェクト', 'local.translation.demo', 'demo.original', ['1.6'], entries, [], languages=['Japanese','German','French'])
        path = root / 'workspace/project.json'
        project.save(path)
        window = Window()
        window.load_project(path)
        window.show()
        window.table.setCurrentIndex(window.proxy.index(1, 0))
        output = Path(__file__).resolve().parents[1] / 'artifacts/gui-smoke.png'
        output.parent.mkdir(exist_ok=True)
        app.processEvents()
        assert window.isVisible()
        assert window.japanese.toPlainText() == entries[1].japanese
        assert window.grab().save(str(output))
        print(f'Qt backend: {app.platformName()}; visible GUI, Japanese detail selection and screenshot verified')
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        return 0

if __name__ == '__main__': raise SystemExit(main())
