"""Shared pytest configuration.

Runs Qt in the offscreen platform and isolates %APPDATA% so tests never touch
the developer's real config/history (AIQuickChat stores both there).
"""

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Isolate config.json / history.json from the real user profile.
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="aiquickchat_tests_")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def chat_window(qapp):
    """A ChatWindow backed by an isolated temp config (new each test)."""
    from ui.chat_window import ChatWindow
    from utils.config_manager import ConfigManager

    cfg_dir = os.path.join(os.environ["APPDATA"], "aiqc_cfg")
    os.makedirs(cfg_dir, exist_ok=True)
    fd, cfg_path = tempfile.mkstemp(suffix=".json", dir=cfg_dir)
    os.close(fd)
    cfg = ConfigManager(cfg_path)
    window = ChatWindow(cfg)
    window.show()
    yield window
    window._quitting = True
    window.close()
