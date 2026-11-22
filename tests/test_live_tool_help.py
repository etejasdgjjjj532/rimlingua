"""Asking the live-game tools for help must not copy or launch the game."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LiveToolHelpTests(unittest.TestCase):
    def test_help_prints_usage_and_does_nothing_else(self):
        for script in ('prepare_live_game.py', 'verify_live_game.py'):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as home:
                # With no game under this HOME, actually running either tool fails; --help must return first.
                result = subprocess.run([sys.executable, str(ROOT / 'tools' / script), '--help'],
                                        capture_output=True, text=True, timeout=60, env=dict(os.environ, HOME=home))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)
                self.assertEqual(list(Path(home).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
