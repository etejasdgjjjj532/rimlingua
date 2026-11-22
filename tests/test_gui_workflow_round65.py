"""Trial output reports remain operable on small logical screens."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CompactTrialReportRound65Tests(unittest.TestCase):
    def test_report_fits_real_small_screen_and_preserves_complete_snapshot(self):
        if os.environ.get('RW65_COMPACT_SCREEN_CHILD'):
            return self.check_compact_report()
        with tempfile.TemporaryDirectory() as temporary:
            for width, height in ((660, 350), (480, 280)):
                config = Path(temporary) / f'{width}.json'
                config.write_text(json.dumps({'screens': [{'name': 'compact', 'width': width,
                    'height': height, 'logicalDpi': 96, 'logicalBaseDpi': 96, 'dpr': 1}]}))
                # QT_QPA_PLATFORM is split on ':', so pass the config relative to cwd (a drive letter would break it).
                env = dict(os.environ, QT_QPA_PLATFORM=f'offscreen:configfile={config.name}',
                           RW65_COMPACT_SCREEN_CHILD='1')
                run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '-v'], env=env, cwd=temporary,
                                     text=True, capture_output=True, timeout=120)  # Windows runners are about twice as slow
                print(f'compact screen {width}x{height}:\n{run.stdout}{run.stderr}', flush=True)
                self.assertEqual(run.returncode, 0, f'{width}x{height} actual Qt screen failed')

    def check_compact_report(self):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QPlainTextEdit
        from rimworld_translator.core import Project, scan_mod
        from rimworld_translator.gui import Window
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            about = source / 'About/About.xml'
            about.parent.mkdir(parents=True)
            about.write_text('<ModMetaData><packageId>test.compact65</packageId><supportedVersions>'
                             '<li>1.6</li><li>1.10</li></supportedVersions></ModMetaData>')
            keyed = source / 'Languages/English/Keyed/a.xml'
            keyed.parent.mkdir(parents=True)
            keyed.write_text('<LanguageData><Safe>Hello</Safe>' + ''.join(
                f'<Unsafe{i}>Hello {{0}}</Unsafe{i}>' for i in range(55)) + '</LanguageData>')
            project = Project.create_versions(source, {v: scan_mod(source, game_version=v) for v in ('1.6', '1.10')})
            for version in ('1.6', '1.10'):
                project.switch_version(version)
                for entry in project.entries:
                    project.set_translation(entry.id, '安全 ' + version if entry.key == 'Safe' else '危険')
            saved = root / ('long-workspace-' + 'w' * 80) / ('nested-' + 'n' * 80) / 'project.json'
            project.save(saved)
            tree = lambda: {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            before_source = {p.name: p.read_bytes() for p in source.rglob('*') if p.is_file()}
            window = Window(settings_path=root / 'settings.json')
            try:
                window.load_project(saved)
                available = window.screen().availableGeometry()
                window.resize(available.width(), available.height())
                window.show()
                app.processEvents()
                window.editor_scroll.ensureWidgetVisible(window.test_export_button)
                app.processEvents()
                def accept_confirmation():
                    box = QApplication.activeModalWidget()
                    self.assertIsInstance(box, QMessageBox)
                    self.assertIn('Q17', box.text())
                    QTest.mouseClick(box.button(QMessageBox.Yes), Qt.LeftButton)
                QTimer.singleShot(0, accept_confirmation)
                QTest.mouseClick(window.test_export_button, Qt.LeftButton)
                app.processEvents()
                report = window.trial_output_report
                self.assertIsNotNone(report)
                self.assertTrue(available.contains(report.frameGeometry()),
                                (available, report.frameGeometry()))
                notices = report.findChild(QPlainTextEdit, 'trialOutputNotices')
                self.assertTrue(notices.isReadOnly())
                text = notices.toPlainText()
                self.assertIn(str(saved.parent / 'mod-test'), text)
                self.assertIn('111.', text)
                notices.verticalScrollBar().setValue(notices.verticalScrollBar().maximum())
                copy = report.findChild(QDialogButtonBox).button(QDialogButtonBox.Close)
                self.assertTrue(available.contains(copy.mapToGlobal(copy.rect().bottomRight())))
                copy_all = report.findChild(type(copy), 'copyTrialOutputNotices')
                self.assertTrue(available.contains(copy_all.mapToGlobal(copy_all.rect().topLeft())))
                window.project.set_translation('Keyed:Keyed:Safe', '後から変更')
                window.dirty = True
                before = tree()
                QTest.mouseClick(copy_all, Qt.LeftButton)
                self.assertEqual(QApplication.clipboard().text(), text)
                QTest.mouseClick(copy, Qt.LeftButton)
                self.assertFalse(report.isVisible())
                window.reopen_trial_output_report()
                app.processEvents()
                self.assertTrue(available.contains(report.frameGeometry()))
                self.assertEqual(notices.toPlainText(), text)
                QTest.keyClick(report, Qt.Key_Escape)
                self.assertFalse(report.isVisible())
                self.assertTrue(window.dirty)
                self.assertEqual(tree(), before)
                self.assertEqual({p.name: p.read_bytes() for p in source.rglob('*') if p.is_file()}, before_source)
            finally:
                window.dirty = False
                window.close()
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
