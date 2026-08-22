"""Unified Tabler Icons helpers built on the `pytablericons` package.

The package ships plain SVG files (outline + filled) and Python enums. Its
`TablerIcons.load()` helper additionally imports `pygame`, which can fail to
build on some Python versions, so the SVG assets are read and rendered here
directly with Qt's SVG renderer. The enums are intentionally not required.
"""

import base64
import importlib.util
import pathlib
import sys
from functools import lru_cache

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QToolButton

DEFAULT_COLOR = "#8A8A96"
DEFAULT_STROKE = 1.6


def _icon_dir() -> pathlib.Path:
    """Return the pytablericons package directory (raises if missing).

    When frozen (PyInstaller), the SVG assets are bundled as data files under
    ``sys._MEIPASS / pytablericons`` (onefile) or next to the executable
    (onedir); in development the installed package directory is used.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        base = pathlib.Path(meipass) if meipass else pathlib.Path(sys.executable).parent
        bundled = base / "pytablericons"
        if (bundled / "icons").is_dir():
            return bundled
    spec = importlib.util.find_spec("pytablericons")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError(
            "pytablericons не установлен. Выполните: pip install -r requirements.txt")
    return pathlib.Path(list(spec.submodule_search_locations)[0])


def _svg_text(name: str, color: str, stroke_width: float, filled: bool) -> str:
    sub = "filled" if filled else "outline"
    filename = name if str(name).endswith(".svg") else f"{name}.svg"
    path = _icon_dir() / "icons" / sub / filename
    if not path.exists():
        raise ValueError(f"Tabler icon «{name}» не найден в pytablericons")
    svg = path.read_text(encoding="utf-8")
    svg = svg.replace("currentColor", color)
    svg = svg.replace('stroke-width="2"', f'stroke-width="{stroke_width}"')
    return svg


@lru_cache(maxsize=512)
def _svg_cached(name: str, color: str, stroke_width: float, filled: bool) -> str:
    return _svg_text(name, color, stroke_width, filled)


def _screen_dpr() -> float:
    try:
        screen = QGuiApplication.primaryScreen()
        return screen.devicePixelRatio() if screen is not None else 1.0
    except Exception:
        return 1.0


def create_pixmap(name: str, size: int = 20, color: str = DEFAULT_COLOR,
                  stroke_width: float = DEFAULT_STROKE, filled: bool = False) -> QPixmap:
    """Render a Tabler icon to a QPixmap at the given logical size."""
    svg = _svg_cached(name, color, stroke_width, filled)
    renderer = QSvgRenderer(svg.encode("utf-8"))
    dpr = max(1.0, _screen_dpr())
    size = max(1, int(size))
    pixmap = QPixmap(int(round(size * dpr)), int(round(size * dpr)))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    return pixmap


def create_icon(name: str, size: int = 20, color: str = DEFAULT_COLOR,
                stroke_width: float = DEFAULT_STROKE, filled: bool = False,
                disabled_color: str = None) -> QIcon:
    """Build a QIcon from a Tabler icon (with an optional disabled variant)."""
    icon = QIcon(create_pixmap(name, size, color, stroke_width, filled))
    if disabled_color:
        icon.addPixmap(
            create_pixmap(name, size, disabled_color, stroke_width, filled),
            QIcon.Disabled)
    return icon


def svg_data_uri(name: str, color: str = DEFAULT_COLOR,
                 stroke_width: float = DEFAULT_STROKE, filled: bool = False) -> str:
    """Base64 data-URI of the icon, for use inside Qt rich-text `<img>` tags."""
    svg = _svg_cached(name, color, stroke_width, filled)
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return "data:image/svg+xml;base64," + encoded


def inline_icon_img(name: str, color: str = DEFAULT_COLOR, size: int = 14,
                    stroke_width: float = DEFAULT_STROKE, filled: bool = False) -> str:
    """An `<img>` tag embedding a Tabler icon, for rich-text labels."""
    uri = svg_data_uri(name, color, stroke_width, filled)
    return (f'<img src="{uri}" width="{size}" height="{size}" '
            'style="vertical-align:middle;">')


class IconButton(QToolButton):
    """A single-style icon button with tooltip, hover and optional check state.

    Hover uses a soft background change (provided by the global stylesheet);
    the icon itself can change colour on the checked state.
    """

    def __init__(self, icon_name: str, tooltip: str = "", size: int = 18,
                 checkable: bool = False, color: str = DEFAULT_COLOR,
                 checked_color: str = None, stroke_width: float = DEFAULT_STROKE,
                 filled: bool = False, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._size = int(size)
        self._color = color
        self._checked_color = checked_color or color
        self._hover_color = None
        self._hovered = False
        self._stroke = stroke_width
        self._filled = filled

        self.setObjectName("iconbtn")
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(checkable)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(self._size + 16, self._size + 16)
        self._render()

    def _current_color(self) -> str:
        if self._hover_color is not None and self._hovered:
            return self._hover_color
        if self.isCheckable() and self.isChecked():
            return self._checked_color
        return self._color

    def _render(self):
        self.setIcon(create_icon(self._icon_name, self._size, self._current_color(),
                                 self._stroke, self._filled))
        self.setIconSize(QSize(self._size, self._size))

    def set_hover_color(self, color: str):
        """Optionally swap the icon colour while the pointer is over the button."""
        self._hover_color = color
        self._render()

    def enterEvent(self, event):
        self._hovered = True
        if self._hover_color is not None:
            self._render()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        if self._hover_color is not None:
            self._render()
        super().leaveEvent(event)

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        self._render()

    def set_color(self, color: str):
        self._color = color
        self._render()

    def set_colors(self, color: str, checked_color: str):
        self._color = color
        self._checked_color = checked_color
        self._render()
