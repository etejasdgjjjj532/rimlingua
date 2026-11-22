"""Test-runner bootstrap inherited by Python children; never loaded by the app."""
import os
from pathlib import Path

state = os.environ.get('RW_TEST_CONFIG_ROOT')
if state:
    # On Windows QSettings normally uses the registry; XDG variables alone do
    # not isolate it. This runs before any test creates QApplication/dialogs.
    try:
        from PySide6.QtCore import QSettings
    except ImportError:
        # A copied Python used as a synthetic game may have no site-packages.
        pass
    else:
        QSettings.setDefaultFormat(QSettings.IniFormat)
        for scope, name in ((QSettings.UserScope, 'qt-user'),
                            (QSettings.SystemScope, 'qt-system')):
            QSettings.setPath(QSettings.IniFormat, scope, str(Path(state) / name))
