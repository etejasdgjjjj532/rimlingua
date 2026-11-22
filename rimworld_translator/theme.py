"""Light and dark appearance for the editor: one set of colour tokens, one stylesheet template.

Colours live only here, so the two modes cannot drift apart. The look follows common desktop
tools: flat panels, thin borders, soft radii, one indigo accent. Each mode uses one tone
throughout: the navigation rail is light in the light mode and dark in the dark mode.
"""
from __future__ import annotations

MODES = ('system', 'light', 'dark')

PALETTES = {
    'light': {
        'window': '#f5f6f8', 'panel': '#ffffff', 'raised': '#eef0f4', 'input': '#ffffff',
        'border': '#e2e5ea', 'border_strong': '#c7ccd5', 'text': '#1a1d23', 'muted': '#5c6575',
        'accent': '#4353d6', 'accent_hover': '#5564e2', 'accent_text': '#ffffff',
        'accent_soft': '#e5e8fc', 'row_alt': '#fafbfc', 'hover': '#eceef3', 'pressed': '#dfe2e9',
        'selection': '#dde1fb', 'selection_text': '#161a47', 'disabled': '#9aa3af',
        'danger': '#c62828', 'ok': '#17753a', 'warn': '#8a5a00', 'info': '#2a4fc4', 'status': '#eef0f4',
        'scroll': '#c6cbd4', 'scroll_hover': '#a9b0bc', 'input_border': '#7f8796',
        'sidebar': '#eceef3', 'sidebar_text': '#1a1d23', 'sidebar_muted': '#5c6575',
        'sidebar_hover': '#dde0e8', 'sidebar_border': '#c7ccd5',
    },
    'dark': {
        'window': '#16181d', 'panel': '#1e2127', 'raised': '#262a31', 'input': '#131519',
        'border': '#2f333b', 'border_strong': '#464c57', 'text': '#e3e5ea', 'muted': '#959ca8',
        'accent': '#8291ff', 'accent_hover': '#9aa6ff', 'accent_text': '#0d1030',
        'accent_soft': '#2a2f5c', 'row_alt': '#21242b', 'hover': '#2c3038', 'pressed': '#363b45',
        'selection': '#343b7c', 'selection_text': '#f1f3ff', 'disabled': '#666c77',
        'danger': '#ff7b72', 'ok': '#56d364', 'warn': '#e3b341', 'info': '#93a8ff', 'status': '#1a1c21',
        'scroll': '#454a54', 'scroll_hover': '#5a606c', 'input_border': '#737b8a',
        'sidebar': '#0f1114', 'sidebar_text': '#e3e5ea', 'sidebar_muted': '#8a909c',
        'sidebar_hover': '#1f2228', 'sidebar_border': '#272a31',
    },
}

# '@token@' placeholders keep the template readable next to Qt's own braces.
_TEMPLATE = """
QMainWindow, QWidget#appRoot, QDialog, QMessageBox { background:@window@; color:@text@; }
QWidget { font-family:'Noto Sans JP','Noto Sans CJK JP','Yu Gothic UI','Meiryo UI','Noto Sans','Segoe UI','DejaVu Sans',sans-serif;
  font-size:@font@pt; color:@text@; }
QToolTip { background:@panel@; color:@text@; border:1px solid @border_strong@; padding:5px 8px; }

QMenuBar { background:@window@; color:@text@; border-bottom:1px solid @border@; padding:2px 4px; }
QMenuBar::item { padding:5px 11px; background:transparent; border-radius:5px; }
QMenuBar::item:selected { background:@hover@; }
QMenu { background:@panel@; color:@text@; border:1px solid @border_strong@; border-radius:8px; padding:5px; }
QMenu::item { padding:7px 24px 7px 14px; border-radius:5px; }
QMenu::item:selected { background:@accent_soft@; color:@text@; }
QMenu::item:disabled { color:@disabled@; }
QMenu::separator { height:1px; background:@border@; margin:5px 8px; }

QScrollArea { border:0; background:@window@; }
QScrollArea > QWidget > QWidget { background:@window@; }
QFrame#pane { background:@panel@; border:1px solid @border@; border-radius:10px; }
QFrame#toolbar { background:@panel@; border:1px solid @border@; border-radius:10px; }
QFrame#stepCard { background:@panel@; border:1px solid @border@; border-radius:10px; }
QLabel#modThumbnail { background:@raised@; border:1px solid @border@; border-radius:8px; color:@muted@; }

QLabel { background:transparent; }
QLabel#brand { color:@text@; font-size:@h2@pt; font-weight:700; }
QLabel#eyebrow { color:@muted@; font-size:@small@pt; font-weight:600; }
QLabel#h1 { color:@text@; font-size:@h1@pt; font-weight:700; }
QLabel#h2 { color:@text@; font-size:@h2@pt; font-weight:700; }
QLabel#muted { color:@muted@; font-size:@small@pt; }
QLabel#helpText { color:@muted@; }
QComboBox#compact { padding:2px 8px; }
QPushButton#compactButton { background:@panel@; padding:3px 10px; }
QLabel#reviewError { color:@danger@; font-weight:600; }
QLabel#advice { color:@warn@; font-size:@small@pt; }
QLabel#muted[over="true"] { color:@danger@; font-weight:600; }
QPushButton#token { background:@panel@; color:@muted@; border:1px solid @border@; border-radius:6px; padding:3px 8px; min-height:18px; }
QPushButton#token[missing="true"] { background:@accent_soft@; color:@accent@; border-color:@accent@; font-weight:600; }
QPushButton#token:hover { border-color:@accent@; }
QTextBrowser#richPreview, QListWidget#suggestList { color:@text@; background:@input@; border:1px solid @input_border@; border-radius:7px; padding:5px 7px; }
QTabWidget#sideTabs::pane { border:0; }
QLabel#counts { color:@muted@; font-size:@small@pt; padding:2px 2px; }
QLabel#done { color:@ok@; font-size:@small@pt; font-weight:600; }
QLabel#selectedKey { color:@accent@; font-weight:600; }
QLabel#stepNumber { color:@accent@; background:@accent_soft@; border-radius:15px; font-weight:700; }

QFrame#sidebar { background:@sidebar@; border:0; border-right:1px solid @border@; }
QScrollArea#sidebarScroll, QScrollArea#sidebarScroll > QWidget { background:@sidebar@; }
QScrollArea#sidebarScroll QScrollBar::handle:vertical { background:@sidebar_border@; }
QFrame#sidebar QLabel { color:@sidebar_text@; }
QFrame#sidebar QLabel#brand { color:@sidebar_text@; }
QFrame#sidebar QLabel#eyebrow, QFrame#sidebar QLabel#muted, QFrame#sidebar QLabel#helpText { color:@sidebar_muted@; }
QFrame#sidebar QLabel#brandMark { color:@accent_text@; background:@accent@; border-radius:8px; font-weight:700; }
QFrame#sidebar QPushButton { background:transparent; color:@sidebar_text@; border:1px solid @sidebar_border@; }
QFrame#sidebar QPushButton:hover { background:@sidebar_hover@; }
QFrame#sidebar QPushButton:disabled { color:@sidebar_muted@; background:transparent; border-color:@sidebar_border@; }
QFrame#sidebar QPushButton#primary { color:@accent_text@; background:@accent@; border:1px solid @accent@; }
QFrame#sidebar QPushButton#primary:hover { background:@accent_hover@; border-color:@accent_hover@; }
QFrame#sidebar QPushButton#ghost { border:1px solid transparent; }
QFrame#sidebar QPushButton#ghost:hover { background:@sidebar_hover@; }
QFrame#sidebar QPushButton:focus { border:2px solid @accent_hover@; }
QFrame#sidebar QPushButton#ghost:disabled { color:@sidebar_muted@; border-color:transparent; }
QFrame#sidebar QProgressBar { background:@sidebar_hover@; border:0; border-radius:3px; }

QPushButton { background:@panel@; border:1px solid @border_strong@; border-radius:7px;
              padding:6px 14px; color:@text@; }
QPushButton:hover { background:@hover@; }
QPushButton:pressed { background:@pressed@; }
QPushButton:focus { border:2px solid @accent@; padding:5px 13px; }
QPushButton:disabled { color:@disabled@; background:@window@; border-color:@border@; }
QPushButton#primary { color:@accent_text@; background:@accent@; border:1px solid @accent@; font-weight:600; }
QPushButton#primary:hover { background:@accent_hover@; border-color:@accent_hover@; }
QPushButton#primary:disabled { background:@accent_soft@; color:@disabled@; border-color:@accent_soft@; }
QPushButton#ghost { background:transparent; border:1px solid transparent; text-align:left; padding:7px 10px; }
QPushButton#ghost:hover { background:@hover@; }
QPushButton#ghost:focus { padding:6px 9px; }
QPushButton#ghost:disabled { color:@disabled@; }
QPushButton#secondary { background:@panel@; }
QPushButton#confirm { color:@accent@; background:@accent_soft@; border:1px solid @accent_soft@; font-weight:600; padding:8px 16px; }
QPushButton#confirm:hover { border-color:@accent@; }
QPushButton#confirm:focus { padding:7px 15px; }
QPushButton#confirm:disabled { color:@disabled@; background:@window@; border-color:@border@; }
QPushButton#chip { background:@panel@; color:@muted@; border:1px solid @border@; border-radius:12px; min-height:18px;
  padding:3px 12px; font-size:@small@pt; }
QPushButton#chip:hover { background:@hover@; color:@text@; }
QPushButton#chip:focus { padding:2px 11px; }
QPushButton#chipClear { background:transparent; border:1px solid transparent; color:@accent@; font-size:@small@pt; padding:3px 8px; }
QPushButton#chipClear:hover { background:@accent_soft@; }
QPushButton#chipClear:focus { padding:2px 7px; }
QPushButton#chip:checked { background:@accent_soft@; color:@accent@; border-color:@accent@; font-weight:600; }
QPushButton#chip:disabled { color:@disabled@; background:@window@; border-color:@border@; }
QPushButton::menu-indicator { subcontrol-position:right center; right:8px; }

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox { color:@text@; background:@input@;
  border:1px solid @input_border@; border-radius:7px; padding:5px 9px;
  selection-background-color:@selection@; selection-color:@selection_text@; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus { border:2px solid @accent@; padding:4px 8px; }
QLineEdit:disabled, QComboBox:disabled { color:@disabled@; background:@window@; }
QPlainTextEdit[readOnly="true"] { background:@raised@; border-color:@border@; }
QComboBox::drop-down { border:0; width:22px; }
QComboBox QAbstractItemView { background:@panel@; color:@text@; border:1px solid @border_strong@;
  selection-background-color:@accent_soft@; selection-color:@text@; outline:0; }
QCheckBox, QRadioButton { spacing:6px; background:transparent; }
QCheckBox::indicator, QAbstractItemView::indicator { width:14px; height:14px; border:1px solid @input_border@;
  border-radius:4px; background:@input@; }
QRadioButton::indicator { width:14px; height:14px; border:1px solid @input_border@; border-radius:8px; background:@input@; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover, QAbstractItemView::indicator:hover { border-color:@accent@; }
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked { background:@accent@; border-color:@accent@; image:url(@icon_check@); }
QCheckBox::indicator:indeterminate, QAbstractItemView::indicator:indeterminate { background:@accent@; border-color:@accent@; image:url(@icon_dash@); }
QRadioButton::indicator:checked { background:@accent@; border-color:@accent@; image:url(@icon_dot@); }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled, QAbstractItemView::indicator:disabled { background:@raised@; border-color:@border@; image:none; }
QCheckBox::indicator:checked:disabled, QAbstractItemView::indicator:checked:disabled { image:url(@icon_check_off@); }
QCheckBox::indicator:indeterminate:disabled, QAbstractItemView::indicator:indeterminate:disabled { image:url(@icon_dash_off@); }
QRadioButton::indicator:checked:disabled { image:url(@icon_dot_off@); }

QTableView, QListView, QListWidget, QTreeView { background:@panel@; alternate-background-color:@row_alt@; color:@text@;
  border:1px solid @border@; border-radius:8px; gridline-color:@border@;
  selection-background-color:@selection@; selection-color:@selection_text@; outline:0; }
QTableView::item { padding:3px 8px; }
QTableView::item:hover:!selected { background:@hover@; }
QHeaderView { background:transparent; }
QHeaderView::section { background:@panel@; color:@muted@; border:0; border-bottom:1px solid @border@;
  padding:7px 9px; font-size:@small@pt; font-weight:600; }
QTableCornerButton::section { background:@panel@; border:0; }

QTabBar::tab { background:transparent; color:@muted@; padding:6px 15px; border:0; border-radius:7px; margin-right:3px; }
QTabBar::tab:hover { color:@text@; background:@hover@; }
QTabBar::tab:selected { color:@accent@; background:@accent_soft@; font-weight:600; }
QTabBar::tab:disabled { color:@disabled@; }
QTreeWidget#entryTree { background:@panel@; }
QTreeView::item { padding:3px 0; }
QTreeView::item:selected { background:@selection@; color:@selection_text@; }
QTreeView::item:hover:!selected { background:@hover@; }
QProgressBar { border:0; border-radius:3px; background:@raised@; color:@text@;
  text-align:center; height:6px; }
QProgressBar::chunk { background:@accent@; border-radius:3px; }
QSplitter::handle { background:transparent; height:7px; width:7px; }
QSplitter::handle:hover { background:@accent_soft@; }
QStatusBar { background:@status@; color:@muted@; border-top:1px solid @border@; }
QStatusBar::item { border:0; }

QScrollBar:vertical { width:12px; background:transparent; margin:0; }
QScrollBar::handle:vertical { background:@scroll@; border-radius:4px; min-height:28px; margin:2px; }
QScrollBar::handle:vertical:hover { background:@scroll_hover@; }
QScrollBar:horizontal { height:12px; background:transparent; margin:0; }
QScrollBar::handle:horizontal { background:@scroll@; border-radius:4px; min-width:28px; margin:2px; }
QScrollBar::handle:horizontal:hover { background:@scroll_hover@; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; width:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
"""


def resolve_mode(setting: str, system_is_dark: bool | None = None) -> str:
    """'light' or 'dark' for a stored 'system' | 'light' | 'dark' preference."""
    if setting in ('light', 'dark'):
        return setting
    return 'dark' if system_is_dark else 'light'


def system_prefers_dark() -> bool:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # an old Qt, or no application yet
        return False


_ICON_DIRS: dict[str, str] = {}


def indicator_icons(mode: str) -> dict[str, str]:
    """Check, dash and dot glyphs for the check box / radio indicators, drawn once per mode into a temp folder.

    Qt style sheets can only point at image files, so the glyphs are painted here from the palette tokens.
    Returns {} when drawing fails; the indicators then still show as a filled accent box.
    """
    mode = 'dark' if mode == 'dark' else 'light'
    try:
        import atexit
        import shutil
        import tempfile
        from pathlib import Path
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QImage, QPainter, QPen
        folder = _ICON_DIRS.get(mode)
        if folder is None:
            folder = tempfile.mkdtemp(prefix=f'rimworld-translator-{mode}-')
            _ICON_DIRS[mode] = folder
            atexit.register(shutil.rmtree, folder, True)
        tokens = PALETTES[mode]
        result = {}
        for suffix, colour in (('', tokens['accent_text']), ('_off', tokens['disabled'])):
            for glyph in ('check', 'dash', 'dot'):
                image = QImage(14, 14, QImage.Format_ARGB32)
                image.fill(Qt.transparent)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.Antialiasing)
                pen = QPen(QColor(colour), 2)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                if glyph == 'check':
                    painter.drawPolyline([QPointF(3.2, 7.2), QPointF(6, 10), QPointF(10.8, 4.2)])
                elif glyph == 'dash':
                    painter.drawLine(QPointF(3.5, 7), QPointF(10.5, 7))
                else:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(colour))
                    painter.drawEllipse(QPointF(7, 7), 3, 3)
                painter.end()
                path = Path(folder) / f'{glyph}{suffix}.png'
                if not image.save(str(path)):
                    return {}
                result[f'icon_{glyph}{suffix}'] = path.as_posix()
        return result
    except Exception:  # no Qt image support: fall back to plain filled boxes
        return {}


def stylesheet(mode: str, font_pt: int = 11) -> str:
    tokens = dict(PALETTES['dark' if mode == 'dark' else 'light'])
    tokens.update(indicator_icons(mode))
    tokens.update(font=str(font_pt), small=str(max(9, font_pt - 1)), h2=str(font_pt), h1=str(font_pt + 7))
    text = _TEMPLATE
    for name, value in tokens.items():
        text = text.replace(f'@{name}@', value)
    import re
    return re.sub(r' ?image:url\(@icon_\w+@\);', '', text)  # glyph files unavailable: plain filled boxes


def application_palette(mode: str):
    """Palette for widgets the stylesheet does not cover (native dialogs, popups)."""
    from PySide6.QtGui import QColor, QPalette
    tokens = PALETTES['dark' if mode == 'dark' else 'light']
    palette = QPalette()
    for role, key in ((QPalette.Window, 'window'), (QPalette.WindowText, 'text'), (QPalette.Base, 'input'),
                      (QPalette.AlternateBase, 'row_alt'), (QPalette.Text, 'text'), (QPalette.Button, 'panel'),
                      (QPalette.ButtonText, 'text'), (QPalette.ToolTipBase, 'raised'), (QPalette.ToolTipText, 'text'),
                      (QPalette.Highlight, 'selection'), (QPalette.HighlightedText, 'selection_text'),
                      (QPalette.PlaceholderText, 'muted'), (QPalette.Link, 'accent')):
        palette.setColor(role, QColor(tokens[key]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(tokens['disabled']))
    return palette
