"""Local, offline, flag-tagged RimWorld mod Preview.png generation.

Original Preview.png is used only as read-only source material. Flags from
flag-icons (MIT), see bundled assets/flags/LICENSE.
"""
from __future__ import annotations
from dataclasses import dataclass
from html import escape
from math import ceil
from pathlib import Path
import re

from .languages import LANGUAGES, validate_languages


def find_source_preview(source: Path) -> Path | None:
    about = source / "About"
    for file in ("Preview.png", "Preview.jpg", "Preview.jpeg"):
        path = about / file
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= 8 * 1024 * 1024:
            return path
    return None


def make_preview_bytes(source: Path, title: str, languages: list[str],use_source: bool=True) -> bytes:
    """Produce a 16:9 PNG with original artwork and a flag badge at lower right."""
    validate_languages(languages)
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, QSize, Qt
    from PySide6.QtGui import QColor, QImage, QImageReader, QLinearGradient, QPainter, QPen
    from PySide6.QtSvg import QSvgRenderer

    width, height = 640, 360
    canvas = QImage(width, height, QImage.Format_ARGB32)
    canvas.fill(QColor("#142133"))
    painter = QPainter(canvas)
    try:
        original = find_source_preview(source) if use_source else None
        source_image = QImage()
        if original:
            reader = QImageReader(str(original))
            reader.setAutoTransform(True)
            reader.setScaledSize(QSize(width * 2, height * 2))
            source_image = reader.read()
        if not source_image.isNull():
            fitted = source_image.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = max(0, (fitted.width()-width)//2)
            y = max(0, (fitted.height()-height)//2)
            painter.drawImage(0, 0, fitted.copy(x,y,width,height))
        else:
            grad = QLinearGradient(0,0,width,height)
            grad.setColorAt(0.0, QColor("#273c58"))
            grad.setColorAt(1.0, QColor("#0b1421"))
            painter.fillRect(0,0,width,height,grad)
            # A quiet fallback, no assets or network required.
            painter.setBrush(QColor("#2b5176"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(-135, -170, 425, 425)
            painter.setBrush(QColor("#184267"))
            painter.drawEllipse(390, 175, 390, 390)

        # Position a subtle rounded rectangle along lower-right, keeping source art visible.
        cols = min(len(languages), 6)
        rows = ceil(len(languages) / 6)
        flag_width, flag_height, gap, inset = 44, 31, 7, 13
        badge_width = inset * 2 + cols * flag_width + (cols-1)*gap
        badge_height = inset * 2 + rows * flag_height + (rows-1)*gap
        xx = width - badge_width - 14
        yy = height - badge_height - 14
        painter.setPen(QPen(QColor("#8296ac"), 1))
        painter.setBrush(QColor(8, 19, 32, 218))
        painter.drawRoundedRect(xx, yy, badge_width, badge_height, 10,10)

        for i,language in enumerate(languages):
            country = LANGUAGES[language][1]
            svg = Path(__file__).resolve().parent / "assets" / "flags" / f"{country}.svg"
            fx = xx + inset + (i % 6)*(flag_width+gap)
            fy = yy + inset + (i // 6)*(flag_height+gap)
            painter.fillRect(fx-1,fy-1,flag_width+2,flag_height+2,QColor("#d9e4f4"))
            renderer = QSvgRenderer(str(svg))
            if renderer.isValid():
                renderer.render(painter, QRectF(fx,fy,flag_width,flag_height))
            else:
                raise ValueError(f"Bundled flag asset missing or invalid: {country}")
    finally:
        painter.end()
    data=QByteArray()
    buffer=QBuffer(data)
    if not buffer.open(QIODevice.WriteOnly) or not canvas.save(buffer,"PNG"):
        raise ValueError("Preview could not be encoded")
    return bytes(data)


# --- Text preview model: how RimWorld lays out line breaks and rich-text tags -------------------------------

@dataclass(frozen=True)
class Span:
    """A run of text with one style. ``token`` marks a {0} / [PAWN_nameDef] placeholder."""
    text: str
    color: str = ""
    bold: bool = False
    italic: bool = False
    size: int | None = None
    token: bool = False


_COLOR_NAMES = {
    "red": "#ff0000", "green": "#008000", "blue": "#0000ff", "white": "#ffffff", "black": "#000000",
    "yellow": "#ffeb04", "cyan": "#00ffff", "magenta": "#ff00ff", "grey": "#808080", "gray": "#808080",
    "orange": "#ffa500", "lime": "#00ff00", "teal": "#008080", "purple": "#800080", "brown": "#a52a2a",
    "maroon": "#800000", "navy": "#000080", "olive": "#808000", "silver": "#c0c0c0", "aqua": "#00ffff",
    "fuchsia": "#ff00ff", "lightblue": "#add8e6", "darkblue": "#0000a0",
}
_PREVIEW_PIECE = re.compile(
    r"(?P<tag><\s*(?P<close>/?)\s*(?P<name>b|i|color|size|br)\s*(?:=\s*(?P<value>[^<>]*?))?\s*/?>)"
    r"|(?P<token>\{(?:\d+|[A-Za-z_]\w*)[^{}]*\}|\[[^\[\]\r\n]+\])"
    r"|(?P<newline>\\n|\r\n|\n|\r)", re.I)


def _color(value: str) -> str:
    value = (value or "").strip().strip("\"'").casefold()
    if value in _COLOR_NAMES:
        return _COLOR_NAMES[value]
    match = re.fullmatch(r"#([0-9a-f]{3,8})", value)
    if match is None or len(match.group(1)) not in (3, 4, 6, 8):
        return ""
    digits = match.group(1)
    if len(digits) <= 4:
        digits = "".join(character * 2 for character in digits)
    return "#" + digits[:6]


def rich_text_model(text: str) -> list[list[Span]]:
    """Split a string into display lines of styled spans, the way the game draws it.

    Handles real and escaped (``\\n``) line breaks, ``<br>``, ``<b>``, ``<i>``, ``<size=N>`` and ``<color=...>``
    (hex or a common colour name). Unknown tags stay visible as text, unclosed tags run to the end, placeholders
    are marked ``token``. This is a preview aid; it does not validate (see qa.py for that).
    """
    lines: list[list[Span]] = [[]]
    stack: list[tuple[str, str]] = []  # (tag name, value)

    def style() -> dict:
        found: dict = {}
        for name, value in stack:
            if name == "b":
                found["bold"] = True
            elif name == "i":
                found["italic"] = True
            elif name == "color":
                found["color"] = _color(value)
            elif name == "size" and value.strip().isdigit():
                found["size"] = int(value)
        return found

    def emit(chunk: str, token: bool = False) -> None:
        if chunk:
            lines[-1].append(Span(chunk, token=token, **style()))

    position = 0
    for match in _PREVIEW_PIECE.finditer(text):
        emit(text[position:match.start()])
        position = match.end()
        if match.group("newline") is not None:
            lines.append([])
        elif match.group("token") is not None:
            emit(match.group("token"), True)
        else:
            name = match.group("name").casefold()
            if name == "br":
                lines.append([])
            elif match.group("close"):
                for index in range(len(stack) - 1, -1, -1):
                    if stack[index][0] == name:
                        del stack[index]
                        break
            else:
                stack.append((name, match.group("value") or ""))
    emit(text[position:])
    return lines


def rich_text_html(text: str, default_color: str = "") -> str:
    """``rich_text_model`` as HTML for a QLabel / QTextBrowser (text is escaped; tokens get a subtle underline)."""
    rendered = []
    for line in rich_text_model(text):
        parts = []
        for span in line:
            css = []
            if span.color or default_color:
                css.append("color:" + (span.color or default_color))
            if span.size:
                css.append(f"font-size:{span.size}px")
            if span.italic:
                css.append("font-style:italic")
            if span.bold:
                css.append("font-weight:bold")
            if span.token:
                css.append("text-decoration:underline dotted")
            body = escape(span.text)
            parts.append(f'<span style="{";".join(css)}">{body}</span>' if css else body)
        rendered.append("".join(parts))
    return "<br>".join(rendered)
