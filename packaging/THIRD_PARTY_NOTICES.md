# Third-party notices

This distribution uses Python, Qt / PySide6, Shiboken, lxml, dnfile, pefile, polib,
the PyInstaller bootloader, and their dependency libraries.
The flag icons are MIT-licensed assets from `flag-icons`. For versions and the full
license texts obtained, see `licenses/dependencies.json` and `licenses/`.

Python is distributed under the PSF license. PySide6, Shiboken and the Qt modules
used here are distributed under their LGPLv3 option. The Qt Company Ltd. and
other contributors retain their copyrights. This archive includes the LGPLv3
and GPLv3 license texts, with additional Qt license texts available in
`licenses/qt/`. Qt includes separately licensed third-party components.

Qt is dynamically linked in the portable `_internal/` directory. Recipients may
replace the Qt/PySide6 libraries with compatible modified versions and debug
those modifications as allowed by the LGPL. This application does not restrict
that right. We have not modified Qt, PySide6, or Python. Upstream sources and
build instructions for the exact version in `dependencies.json` are available:

- Qt source releases: https://download.qt.io/official_releases/qt/
- Qt for Python source releases: https://download.qt.io/official_releases/QtForPython/
- Qt for Python repository: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Python source releases: https://www.python.org/downloads/source/
- Qt license/attribution reference: https://doc.qt.io/qt-6/licensing.html
- Qt for Python licensing: https://doc.qt.io/qtforpython-6/licenses.html
- PyInstaller bootloader exception: https://pyinstaller.org/en/stable/license.html

PyInstaller permits distributing generated executables under the application's
chosen license through its bootloader exception. Its complete COPYING text is
included when supplied by the installed wheel.

The editor itself is released under the Mozilla Public License 2.0 (`LICENSE`). These third-party notices do not
grant a license to RimWorld or any MOD. No RimWorld/game files, source MOD assets, project.json files or
translation workspaces are included. When RimWorld is installed, the editor reads its assembly's metadata and
data folder names once and keeps a table of class, field and Def names in the user's own cache folder
(`game-table/`, outside this program). That table is created on the user's machine and is not distributed.
Source MOD previews and generated translations can have separate copyright obligations; obtain the
author's permission before publishing those assets.

Portions of the materials used to create this content/mod are trademarks and/or copyrighted works of Ludeon Studios Inc. All rights reserved by Ludeon. This content/mod is not official and is not endorsed by Ludeon.

This is a community-made tool, distributed free of charge.
