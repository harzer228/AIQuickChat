"""AI Quick Chat — global floating AI assistant for Windows.

Entry point. Runs in the background, shows the chat window on a global
hotkey (Ctrl+Space by default) above any application.
"""

import ctypes
import sys

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from config import APP_NAME, APP_VERSION, DEFAULT_STT_HOTKEY
from ui.chat_window import ChatWindow
from ui.icons import create_icon
from ui.settings_window import SettingsWindow
from utils.config_manager import ConfigManager, set_start_with_windows
from utils.hotkey import HotkeyConflictError, HotkeyManager
from utils.i18n import detect_system_language, set_language, t


class AppController(QObject):
    exitRequested = Signal()

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.config = ConfigManager()
        set_language(self.config.get("appearance", "language", "")
                     or detect_system_language())
        self.hotkeys = HotkeyManager()
        self.hotkeys_stt = HotkeyManager(hotkey_id=0x5A4D)
        app.installNativeEventFilter(self.hotkeys)
        app.installNativeEventFilter(self.hotkeys_stt)

        self.chat = ChatWindow(self.config)
        self.settings = SettingsWindow(
            self.config, hotkey_validator=self._validate_hotkey,
            stt_hotkey_validator=self._validate_stt_hotkey)

        self._setup_signals()
        self._setup_tray()
        self._register_hotkey(show_error=False)
        self._register_stt_hotkey(show_error=False)
        self._apply_autostart()

    # ------------------------------------------------------------- wiring

    def _setup_signals(self):
        self.chat.openSettings.connect(self.show_settings)
        self.chat.newChatRequested.connect(self.chat.start_new_chat)
        self.chat.exitRequested.connect(self._on_chat_exit_requested)
        self.settings.applied.connect(self._on_settings_applied)
        self.hotkeys.set_callback(self.toggle_chat)
        self.hotkeys_stt.set_callback(self.open_chat_with_stt)
        self.exitRequested.connect(self._quit)

    def _on_chat_exit_requested(self):
        if self.config.get("general", "close_to_tray", True):
            self.chat.hide_animated()
        else:
            self.exitRequested.emit()

    # --------------------------------------------------------------- tray

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self._make_icon(), self.app)
        self.tray.setToolTip(f"{APP_NAME} v{APP_VERSION}")
        menu = QMenu()
        icon_color = "#8A8A96"

        toggle_act = QAction(t("tray.show_hide"), menu)
        toggle_act.setIcon(create_icon("arrows-diagonal-2", 16, icon_color, 1.6))
        toggle_act.triggered.connect(self.toggle_chat)
        menu.addAction(toggle_act)

        new_act = QAction(t("tray.new_chat"), menu)
        new_act.setIcon(create_icon("plus", 16, icon_color, 1.6))
        new_act.triggered.connect(self.chat.start_new_chat)
        menu.addAction(new_act)

        settings_act = QAction(t("tray.settings"), menu)
        settings_act.setIcon(create_icon("settings", 16, icon_color, 1.6))
        settings_act.triggered.connect(self.show_settings)
        menu.addAction(settings_act)

        menu.addSeparator()

        quit_act = QAction(t("tray.quit"), menu)
        quit_act.setIcon(create_icon("power", 16, icon_color, 1.6))
        quit_act.triggered.connect(self.exitRequested.emit)
        menu.addAction(quit_act)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_chat()

    def _make_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#4F7CFF"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(2, 2, 60, 60, 16, 16)
        painter.setPen(QColor("#FFFFFF"))
        font = QFont("Segoe UI", 22, QFont.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "AI")
        painter.end()
        return QIcon(pixmap)

    # -------------------------------------------------------------- hotkey

    def _validate_hotkey(self, combo: str):
        return self._validate_combo(combo, self.hotkeys)

    def _validate_stt_hotkey(self, combo: str):
        return self._validate_combo(combo, self.hotkeys_stt)

    def _validate_combo(self, combo: str, manager):
        # The currently registered combo is known to work — no need to re-test
        # it (Windows forbids registering the same combo twice in one thread).
        from utils.hotkey import humanize_combo
        if (manager.combo and humanize_combo(manager.combo).lower()
                == humanize_combo(combo).lower()):
            return True, None
        try:
            test = HotkeyManager()
            test.register(combo)
            test.unregister()
            return True, None
        except (HotkeyConflictError, ValueError) as e:
            return False, str(e)

    def _register_hotkey(self, show_error=True):
        combo = self.config.get_hotkey()
        try:
            # Bind the hotkey to the chat window's native handle so WM_HOTKEY
            # is reliably delivered even when the window is hidden to the tray.
            hwnd = int(self.chat.winId())
            self.hotkeys.register(combo, hwnd=hwnd)
            return True
        except (HotkeyConflictError, ValueError) as e:
            if show_error:
                QMessageBox.warning(
                    None, t("settings.hotkey_warning_title"),
                    t("hotkey.register_failed", combo=combo, error=e))
            return False

    def _register_stt_hotkey(self, show_error=True):
        combo = self.config.get_stt_hotkey() or DEFAULT_STT_HOTKEY
        try:
            hwnd = int(self.chat.winId())
            self.hotkeys_stt.register(combo, hwnd=hwnd)
            return True
        except (HotkeyConflictError, ValueError) as e:
            if show_error:
                QMessageBox.warning(
                    None, t("settings.hotkey_warning_title"),
                    t("hotkey.register_failed", combo=combo, error=e))
            return False

    # ---------------------------------------------------------------- chat

    def toggle_chat(self):
        if self.chat.isVisible():
            self.chat.hide_animated()
        else:
            self.chat.position_centered()
            self.chat.show_animated()
            if self.config.get("general", "open_new_tab_on_hotkey", True):
                self.chat.start_new_chat()

    def open_chat_with_stt(self):
        """Open Chat + auto-start Speech-to-Text (dedicated hotkey)."""
        self.chat.open_with_dictation()

    def show_settings(self):
        self.settings.load_from_config()
        self.settings.position_centered()
        self.settings.show_animated()

    # ----------------------------------------------------------- settings

    def _on_settings_applied(self):
        self._apply_autostart()
        set_language(self.config.get("appearance", "language", "")
                     or detect_system_language())
        if not self._register_hotkey(show_error=True):
            QMessageBox.warning(
                None, t("settings.hotkey_warning_title"), t("hotkey.not_registered"))
        self._register_stt_hotkey(show_error=True)
        self.chat.apply_config_changes()

    def _apply_autostart(self):
        set_start_with_windows(
            bool(self.config.get("general", "start_with_windows", False)))

    # ----------------------------------------------------------------- quit

    def _quit(self):
        self.chat._quitting = True
        self.settings._quitting = True
        self.chat.shutdown()
        self.chat._save_history()
        self.config.save()
        self.tray.hide()
        self.chat.close()
        self.settings.close()
        self.app.quit()


def main():
    # Prevent the DPI scaling warning clutter.
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # Make sure the window icon shows in the taskbar/tray.
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)

    controller = AppController(app)

    # Show the chat once at startup so the user sees the assistant.
    QTimer.singleShot(350, controller.toggle_chat)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
