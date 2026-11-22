"""The source launcher supports an explicitly selected development Python."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class LauncherTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'Bash source launcher is Linux-only')
    def test_selected_interpreter_receives_project_path_without_splitting(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            interpreter = Path(directory) / 'python probe'
            interpreter.write_text(f'#!{sys.executable}\nimport json, os, sys\n'
                                   'print(json.dumps({"cwd": os.getcwd(), "argv": sys.argv[1:]}))\n')
            interpreter.chmod(0o700)
            result = subprocess.run(['bash', str(root / 'run.sh'), '/translation work/project.json'],
                                    cwd=directory, env=dict(os.environ, RW_TRANSLATOR_PYTHON=str(interpreter)),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {
                'cwd': str(root), 'argv': ['-m', 'rimworld_translator', '/translation work/project.json']})
