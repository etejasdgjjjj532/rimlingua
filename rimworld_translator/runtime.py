"""Identify runtime evidence without treating Wine as native Windows."""
import ctypes
import os
import sys


def _wine_version() -> str | None:
    if sys.platform != 'win32':
        return None
    try:
        function = ctypes.WinDLL('ntdll').wine_get_version
        function.restype = ctypes.c_char_p
        function.argtypes = []
        value = function()
        return value.decode('utf-8', errors='replace') if value else 'unknown'
    except (AttributeError, OSError):
        return None


def runtime_evidence(qt_backend: str | None = None) -> dict:
    version = _wine_version()
    wine = sys.platform == 'win32' and (version is not None or any(
        os.environ.get(name) for name in ('WINEPREFIX', 'WINELOADERNOEXEC', 'WINEDLLPATH')))
    windows = sys.platform == 'win32'
    linux = sys.platform.startswith('linux')
    native_os = (windows and not wine) or linux
    native_gui = ((windows and not wine and qt_backend == 'windows')
                  or (linux and qt_backend in ('xcb', 'wayland')))
    information = {'windows_product_type': None, 'windows_version': None, 'windows_name': None}
    client = False
    if windows:
        try:
            windows_version = sys.getwindowsversion()
            numbers = windows_version.platform_version
            client = windows_version.product_type == 1 and numbers[0] == 10 and numbers[2] >= 10240
            information.update(windows_product_type=windows_version.product_type, windows_version=list(numbers),
                               windows_name=('Windows 11' if numbers[2] >= 22000 else 'Windows 10') if client else 'Windows Server' if windows_version.product_type != 1 else 'Other Windows client')
        except (AttributeError, OSError):
            pass
    return {'os': sys.platform, 'runtime': 'wine' if wine else 'windows' if windows else 'linux' if linux else sys.platform,
            'wine': wine, 'wine_version': version, 'native_os': native_os,
            'qt_backend': qt_backend, 'native_gui': native_gui,
            'native_windows_client_gui': windows and client and native_gui, **information}
