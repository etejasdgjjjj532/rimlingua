"""Run unittest with disposable Qt state and this checkout in every interpreter."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    # Windows hands out 8.3 short temporary paths (RUNNER~1) while the code resolves paths to the long form;
    # give this process and every child the long form so expected and returned paths compare equal.
    temporary_root = str(Path(tempfile.gettempdir()).resolve())
    tempfile.tempdir = temporary_root
    with tempfile.TemporaryDirectory(prefix='rimworld-tests-') as directory:
        state = Path(directory)
        environment = dict(os.environ)
        for variable in ('TMP', 'TEMP', 'TMPDIR'):
            environment[variable] = temporary_root
        for variable, folder in (('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                                 ('XDG_CACHE_HOME', 'cache'), ('XDG_STATE_HOME', 'state')):
            path = state / folder
            path.mkdir()
            environment[variable] = str(path)
        environment['RW_TEST_CONFIG_ROOT'] = str(state)
        environment['RW_TRANSLATOR_SETTINGS'] = str(state / 'settings.json')
        # Children started as scripts otherwise prefer an installed older wheel.
        environment['PYTHONPATH'] = os.pathsep.join((str(root / 'tools/test_support'), str(root)))
        # Synthetic game tests copy Python outside its installation directory.
        environment['PYTHONHOME'] = sys.base_prefix
        environment.setdefault('QT_QPA_PLATFORM', 'offscreen')
        # The interface language follows the OS by default; pin the OS language so results do not depend on this
        # machine. The variable works on every platform (Qt on Windows ignores LANG); LANG covers other locale uses.
        for variable in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES'):
            environment.pop(variable, None)
        environment['LANG'] = 'ja_JP.UTF-8'
        environment['RW_TRANSLATOR_SYSTEM_LANGUAGES'] = 'ja-JP,ja'
        arguments = sys.argv[1:] or ['discover', '-s', 'tests', '-v']
        command = ([sys.executable, *arguments[1:]] if arguments[0] == '--script'
                   else [sys.executable, '-m', 'unittest', *arguments])
        return subprocess.run(command,
                              cwd=root, env=environment).returncode


if __name__ == '__main__':
    raise SystemExit(main())
