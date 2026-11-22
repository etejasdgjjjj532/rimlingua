"""The supported runner must isolate Qt settings, including child interpreters."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class IsolatedRunnerTests(unittest.TestCase):
    def test_dialog_and_child_settings_stay_in_temporary_test_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / 'result.json'
            fixture = root / 'test_probe.py'
            fixture.write_text('''import json, os, subprocess, sys, unittest
from pathlib import Path
class Probe(unittest.TestCase):
 def test_isolation(self):
  from PySide6.QtCore import QSettings, QCoreApplication, QEvent
  from PySide6.QtWidgets import QApplication, QFileDialog
  import rimworld_translator.gui
  app = QApplication([])
  dialog = QFileDialog()
  dialog.setOption(QFileDialog.DontUseNativeDialog, True)
  dialog.deleteLater()
  QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
  app.processEvents()
  code = "from PySide6.QtCore import QSettings; print(QSettings(QSettings.UserScope, 'QtProject').fileName())"
  child = subprocess.check_output([sys.executable, '-c', code], text=True).strip()
  path = QSettings(QSettings.UserScope, 'QtProject').fileName()
  Path(os.environ['PROBE_RESULT']).write_text(json.dumps({'parent': path, 'child': child,
   'source': rimworld_translator.gui.__file__, 'settings': os.environ['RW_TRANSLATOR_SETTINGS'],
   'root': os.environ['RW_TEST_CONFIG_ROOT']}))
''', encoding='utf-8')
            env = dict(os.environ, PROBE_RESULT=str(result),
                       RW_TRANSLATOR_SETTINGS=str(root / 'personal.json'))
            run = subprocess.run([sys.executable, str(ROOT / 'tools/run_tests.py'),
                                  'discover', '-s', str(root), '-v'],
                                 env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            data = json.loads(result.read_text())
            self.assertEqual(Path(data['source']).resolve(), ROOT / 'rimworld_translator/gui.py')
            # QSettings(UserScope, 'QtProject') always uses the native backend, which on Windows is the registry and
            # cannot be redirected into the test root; only the editor's own settings file is isolated there.
            for field in (('settings',) if os.name == 'nt' else ('parent', 'child', 'settings')):
                self.assertTrue(Path(data[field]).is_relative_to(data['root']), data)
            self.assertFalse((root / 'personal.json').exists())
            self.assertFalse(Path(data['root']).exists(), 'Temporary test state must be cleaned up')

    def test_runner_preserves_failure_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'test_failure.py').write_text(
                'import unittest\nclass Failure(unittest.TestCase):\n'
                ' def test_failure(self): self.fail("intentional probe failure")\n')
            run = subprocess.run([sys.executable, str(ROOT / 'tools/run_tests.py'),
                                  'discover', '-s', directory],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            self.assertIn('intentional probe failure', run.stderr)
