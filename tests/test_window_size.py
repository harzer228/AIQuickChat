"""Window size: shrink-proof geometry, edge-resize hit test, settings limits."""

from PySide6.QtCore import QEventLoop, QPoint, QTimer

from config import (
    WINDOW_MAX_HEIGHT,
    WINDOW_MAX_WIDTH,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from ui import chat_window as cw


def _pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_hidden_window_geometry_resets_to_resting(chat_window):
    """After a full hide the hidden window sits at its full-size geometry."""
    chat_window.show_animated()
    _pump(400)
    resting = chat_window._resting_geometry()

    chat_window.hide_animated()
    _pump(400)
    assert not chat_window.isVisible()
    geo = chat_window.geometry()
    assert abs(geo.width() - resting.width()) <= 1
    assert abs(geo.height() - resting.height()) <= 1


def test_show_during_hide_keeps_window_visible(chat_window):
    """Reopening mid-hide must not let the stopped hide animation win.

    QAbstractAnimation.stop() emits finished(); the old code connected that
    straight to hide(), so a rapid toggle hid the freshly shown window.
    """
    chat_window.show_animated()
    _pump(400)

    chat_window.hide_animated()
    _pump(40)  # mid-hide (130 ms)
    chat_window.show_animated()
    _pump(300)
    assert chat_window.isVisible()


def test_edge_hit_zones(chat_window):
    w, h = chat_window.width(), chat_window.height()
    hit = chat_window._edge_hit
    assert hit(QPoint(2, 2)) == cw.HTTOPLEFT
    assert hit(QPoint(w - 3, 2)) == cw.HTTOPRIGHT
    assert hit(QPoint(2, h - 3)) == cw.HTBOTTOMLEFT
    assert hit(QPoint(w - 3, h - 3)) == cw.HTBOTTOMRIGHT
    assert hit(QPoint(2, h // 2)) == cw.HTLEFT
    assert hit(QPoint(w - 3, h // 2)) == cw.HTRIGHT
    assert hit(QPoint(w // 2, 2)) == cw.HTTOP
    assert hit(QPoint(w // 2, h - 3)) == cw.HTBOTTOM
    assert hit(QPoint(w // 2, h // 2)) == 0
    assert hit(QPoint(30, 30)) == 0


def test_window_size_hard_bounds(chat_window):
    chat_window.resize(WINDOW_MAX_WIDTH + 500, WINDOW_MAX_HEIGHT + 500)
    assert chat_window.width() <= WINDOW_MAX_WIDTH
    assert chat_window.height() <= WINDOW_MAX_HEIGHT
    chat_window.resize(WINDOW_MIN_WIDTH - 100, WINDOW_MIN_HEIGHT - 100)
    assert chat_window.width() >= WINDOW_MIN_WIDTH
    assert chat_window.height() >= WINDOW_MIN_HEIGHT


def test_apply_config_clamps_out_of_range_size(chat_window):
    chat_window.config.set_window("width", 5000)
    chat_window.config.set_window("height", 10)
    chat_window._apply_config()
    assert chat_window.width() == WINDOW_MAX_WIDTH
    assert chat_window.height() == WINDOW_MIN_HEIGHT
    # The clamped size is written back so the settings stay consistent.
    assert chat_window.config.get_window("width") == WINDOW_MAX_WIDTH
    assert chat_window.config.get_window("height") == WINDOW_MIN_HEIGHT


def test_apply_config_applies_configured_size(chat_window):
    chat_window.config.set_window("width", 560)
    chat_window.config.set_window("height", 720)
    chat_window._apply_config()
    assert chat_window.width() == 560
    assert chat_window.height() == 720


def test_settings_spinboxes_clamp_and_save(chat_window, monkeypatch):
    import ui.settings_window as sw
    monkeypatch.setattr(sw, "set_start_with_windows", lambda enabled: None)

    win = sw.SettingsWindow(chat_window.config)
    win.applied.connect(chat_window.apply_config_changes)  # wired by main.AppController
    win.load_from_config()
    assert win.win_width.value() == chat_window.width()
    assert win.win_height.value() == chat_window.height()

    win.win_width.setValue(WINDOW_MAX_WIDTH + 100)  # clamped by the spin range
    win.win_height.setValue(WINDOW_MIN_HEIGHT - 100)
    win._save()
    assert chat_window.config.get_window("width") == WINDOW_MAX_WIDTH
    assert chat_window.config.get_window("height") == WINDOW_MIN_HEIGHT

    # applied -> the live window is resized to the saved values
    assert chat_window.width() == WINDOW_MAX_WIDTH
    assert chat_window.height() == WINDOW_MIN_HEIGHT
