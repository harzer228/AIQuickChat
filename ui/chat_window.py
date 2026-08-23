"""Main floating chat window."""

import base64
import ctypes
import html
import json
import re
import threading
import traceback
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QEasingCurve,
    QIODevice,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QGuiApplication, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from api.deepseek import DeepSeekClient
from api.errors import APIError, GenerationCancelled
from api.vision import CloudflareVisionClient, build_deepseek_image_message, build_vision_prompt
from api.web_search import WebSearchClient, build_search_context
from config import (
    DEFAULT_APP_URL,
    DEFAULT_MODEL,
    DEFAULT_STT_SILENCE_TIMEOUT,
    DEFAULT_VISION_MODEL,
    DEFAULT_WEBSEARCH_PROVIDER,
    DEFAULT_WEBSEARCH_URL,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    WINDOW_MAX_HEIGHT,
    WINDOW_MAX_WIDTH,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    history_path,
)
from stt.engine import SpeechWorker, device_exists, model_is_valid
from ui.icons import IconButton, create_icon, inline_icon_img
from ui.widgets import (
    Bubble,
    DragHandle,
    ImagePreview,
    ThinkingIndicator,
    animate_fade_in,
    animate_fade_out,
    animate_fade_slide_in,
    make_stylesheet,
    set_markdown_colors,
    smooth_scroll,
    theme_colors,
)
from utils.config_manager import ConfigManager
from utils.file_reader import DOC_EXTENSIONS, DocumentError, read_document
from utils.i18n import t

SYSTEM_PROMPT = (
    "Ты — AI Quick Chat, быстрый и полезный ИИ-ассистент для Windows. "
    "Отвечай кратко, точно и по существу, на языке пользователя. "
    "Если пользователь спрашивает про изображение — отвечай на основе описания изображения."
)

SEARCH_DECISION_SYSTEM = (
    "You are a search-decision engine for a chat assistant. "
    "Decide whether answering the user's question requires up-to-date information "
    "from the web. Reply with ONLY a JSON object:\n"
    '{"needs_search": true/false, "query": "<concise search query in the user\'s language>"}\n'
    "Set needs_search to true when the question is about: recent news, current prices, "
    "latest software versions, documentation, current events, time-sensitive information, "
    "a specific website, company facts, or fresh technical data.\n"
    "Set needs_search to false for stable general-knowledge or coding questions "
    "that do not depend on current facts (e.g. \"What is Python?\", "
    "\"How does a for loop work?\", \"Write a sorting function\").\n"
    "Do not output anything except the JSON object."
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# Native edge-resize via WM_NCHITTEST (frameless window).
WM_NCHITTEST = 0x0084
HTLEFT, HTRIGHT = 10, 11
HTTOP, HTTOPLEFT, HTTOPRIGHT = 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
RESIZE_MARGIN = 8  # px from the window border that starts an edge resize


def _parse_search_decision(reply: str):
    """Parse the DeepSeek search-decision JSON. Defaults to searching on failure."""
    text = (reply or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    needs_search = True
    query = ""
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            needs_search = bool(obj.get("needs_search", True))
            query = (obj.get("query") or "").strip()
        except Exception:
            pass
    return needs_search, query


class _ChatTab(QWidget):
    """A single conversation tab: own messages, history and scroll area."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.conversation = []
        self.links = []  # [(bubble, conversation_entry), ...] in display order
        self._pending_vision_bubble = None  # user bubble awaiting its vision entry
        self._assistant_bubble = None
        self._thinking = None
        self._thinking_container = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(4, 2, 4, 2)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addStretch(1)
        self.scroll.setWidget(self.messages_container)
        lay.addWidget(self.scroll)


class _TaskState:
    """One in-flight generation task bound to its tab (parallel per tab)."""

    def __init__(self, task_id: int, tab: "_ChatTab"):
        self.id = task_id
        self.tab = tab
        self.cancel_event = threading.Event()
        self.deepseek = None    # cancellable client, set from the worker thread
        self.sources = None
        self.thread = None
        self.worker = None
        self.watchdog = None


class ChatWindow(QWidget):
    openSettings = Signal()
    exitRequested = Signal()
    newChatRequested = Signal()

    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        self.pending_image = None       # QImage to send
        self.pending_image_name = ""
        self.pending_docs = []          # [(name, text), ...] attached documents
        self._anim = None
        self._geo_anim = None        # in-flight open/hide scale animation
        self._geo_anim_lock = False  # True while setGeometry() prepares an animation
        self._rest_geo = None        # full-size geometry, never shrunk by animations
        self._quitting = False
        self._tasks = {}             # task_id -> _TaskState (at most one per tab)
        self._task_id = 0

        # Speech-to-Text (dictation) state
        self._stt_active = False
        self._stt_dictating = False
        self._stt_thread = None
        self._stt_worker = None
        self._stt_base_text = ""
        self._stt_prior_readonly = False
        self._stt_send_after = False
        self._stt_error_occurred = False
        self._stt_pending_result = ""
        self._stt_dots = 0

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("AI Quick Chat")
        # Hard size bounds — nothing (animations, edge resize, config) can
        # push the window outside these limits.
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.setMaximumSize(WINDOW_MAX_WIDTH, WINDOW_MAX_HEIGHT)

        self._build_ui()
        self._apply_config()
        self._load_history()
        if self.tabs_widget.count() == 0:
            self._add_tab()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.card = QFrame()
        self.card.setObjectName("card")
        outer.addWidget(self.card)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(8)

        # -- header ---------------------------------------------------------
        self.header = DragHandle()
        header_lay = QHBoxLayout(self.header)
        header_lay.setContentsMargins(6, 2, 2, 2)
        header_lay.setSpacing(6)

        self.logo_label = QLabel()
        self.logo_label.setFixedSize(22, 22)
        header_lay.addWidget(self.logo_label)

        self.title_label = QLabel("AI Quick Chat")
        self.title_label.setObjectName("title")
        header_lay.addWidget(self.title_label)

        self.new_chat_btn = IconButton("plus", tooltip=t("chat.new_tab_tooltip"))
        self.new_chat_btn.clicked.connect(self.start_new_chat)
        header_lay.addStretch(1)
        header_lay.addWidget(self.new_chat_btn)

        self.settings_btn = IconButton("settings", tooltip=t("chat.settings_tooltip"))
        self.settings_btn.clicked.connect(self.openSettings.emit)
        header_lay.addWidget(self.settings_btn)

        self.close_btn = IconButton("x", tooltip=t("chat.close_tooltip"))
        self.close_btn.clicked.connect(self._on_close_clicked)
        header_lay.addWidget(self.close_btn)

        lay.addWidget(self.header)

        header_sep = QFrame()
        header_sep.setObjectName("header_sep")
        header_sep.setFixedHeight(1)
        lay.addWidget(header_sep)

        # -- tabs ------------------------------------------------------------
        self.tabs_widget = QTabWidget()
        self.tabs_widget.setDocumentMode(True)
        self.tabs_widget.setMovable(True)
        self.tabs_widget.currentChanged.connect(self._on_tab_changed)
        self.tabs_widget.setObjectName("chat_tabs")
        lay.addWidget(self.tabs_widget, 1)

        # -- input ------------------------------------------------------------
        self.preview = ImagePreview(max_height=110)
        self.preview.removeRequested.connect(self._clear_image)
        self.preview.hide()
        lay.addWidget(self.preview)

        # Attached-document chips (pdf/docx/text files).
        self.doc_chips_row = QWidget()
        chips_lay = QHBoxLayout(self.doc_chips_row)
        chips_lay.setContentsMargins(0, 0, 0, 0)
        chips_lay.setSpacing(6)
        chips_lay.addStretch(1)
        self.doc_chips_row.hide()
        lay.addWidget(self.doc_chips_row)

        # Web Search status banner (Searching the web... / Found N sources).
        self.web_banner = QFrame()
        self.web_banner.setObjectName("websearch_banner")
        self.web_banner.hide()
        web_lay = QHBoxLayout(self.web_banner)
        web_lay.setContentsMargins(10, 5, 10, 5)
        web_lay.setSpacing(6)
        self.web_banner_icon = QLabel()
        web_lay.addWidget(self.web_banner_icon)
        self.web_banner_text = QLabel("Web Search")
        self.web_banner_text.setObjectName("muted")
        web_lay.addWidget(self.web_banner_text)
        web_lay.addStretch(1)
        lay.addWidget(self.web_banner)

        # Composer: attachments, input, mic and send in one rounded bar.
        self.composer = QFrame()
        self.composer.setObjectName("composer")
        composer_lay = QHBoxLayout(self.composer)
        composer_lay.setContentsMargins(7, 5, 7, 5)
        composer_lay.setSpacing(4)

        self.web_search_btn = IconButton(
            "world-search", tooltip=t("chat.web_search_tooltip"),
            size=18, checkable=True)
        self.web_search_btn.setChecked(self._web_search_enabled())
        self.web_search_btn.toggled.connect(self._toggle_web_search)
        composer_lay.addWidget(self.web_search_btn)

        self.attach_btn = IconButton(
            "paperclip", tooltip=t("chat.attach_tooltip"))
        self.attach_btn.clicked.connect(self._on_attach_clicked)
        composer_lay.addWidget(self.attach_btn)

        self.input = QTextEdit()
        self.input.setObjectName("input")
        self.input.setPlaceholderText(t("chat.input_placeholder"))
        self.input.setAcceptRichText(False)
        self.input.setMinimumHeight(40)
        self.input.setMaximumHeight(120)
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input.textChanged.connect(self._update_send_state)
        self.input.textChanged.connect(self._auto_resize_input)
        self.input.installEventFilter(self)
        composer_lay.addWidget(self.input, 1)

        self.mic_btn = QPushButton()
        self.mic_btn.setObjectName("mic")
        self.mic_btn.setCursor(Qt.PointingHandCursor)
        self.mic_btn.setIconSize(QSize(16, 16))
        self.mic_btn.setFixedSize(34, 34)
        self.mic_btn.clicked.connect(self._on_mic_clicked)
        self.mic_btn.setEnabled(self._stt_enabled())
        composer_lay.addWidget(self.mic_btn)

        self.send_btn = QPushButton()
        self.send_btn.setObjectName("send")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self._on_send_or_stop)
        self.send_btn.setEnabled(False)
        self.send_btn.setIconSize(QSize(20, 20))
        composer_lay.addWidget(self.send_btn)

        lay.addWidget(self.composer)
        # QTextEdit's default sizeHint is ~4 lines tall; normalize to one line
        # before the first layout pass.
        self._auto_resize_input()

        # Speech-to-Text status row (Listening... / Stopping... / errors).
        self.stt_status_row = QWidget()
        stt_lay = QHBoxLayout(self.stt_status_row)
        stt_lay.setContentsMargins(6, 0, 6, 0)
        stt_lay.setSpacing(6)
        self.stt_status_icon = QLabel()
        stt_lay.addWidget(self.stt_status_icon)
        self.stt_status = QLabel()
        self.stt_status.setObjectName("hint")
        stt_lay.addWidget(self.stt_status)
        stt_lay.addStretch(1)
        self.stt_status_row.hide()
        lay.addWidget(self.stt_status_row)

        self._stt_dots_timer = QTimer(self)
        self._stt_dots_timer.setInterval(450)
        self._stt_dots_timer.timeout.connect(self._stt_tick_dots)

        self.hint_label = QLabel(t("chat.hint"))
        self.hint_label.setObjectName("hint")
        self.hint_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.hint_label)

    # ------------------------------------------------------------- styling

    def _apply_config(self):
        theme = self.config.get("appearance", "theme", "dark")
        colors = theme_colors(theme)
        set_markdown_colors(colors)
        self.setStyleSheet(make_stylesheet(theme))
        self._apply_icon_colors()
        self._rerender_bubbles()
        self._refresh_doc_chips()
        self.setWindowOpacity(self._target_opacity())
        width = int(self.config.get_window("width", DEFAULT_WINDOW_WIDTH)
                    or DEFAULT_WINDOW_WIDTH)
        height = int(self.config.get_window("height", DEFAULT_WINDOW_HEIGHT)
                     or DEFAULT_WINDOW_HEIGHT)
        width = max(WINDOW_MIN_WIDTH, min(WINDOW_MAX_WIDTH, width))
        height = max(WINDOW_MIN_HEIGHT, min(WINDOW_MAX_HEIGHT, height))
        self.resize(width, height)
        # Keep the canonical resting geometry in sync even while hidden
        # (a resize of a hidden window may not fire resizeEvent right away).
        geo = self.geometry()
        self._rest_geo = QRect(geo.x(), geo.y(), self.width(), self.height())

    def _rerender_bubbles(self):
        """Re-render markdown bubbles so theme-baked colors (tables) refresh."""
        for i in range(self.tabs_widget.count()):
            tab = self.tabs_widget.widget(i)
            if not isinstance(tab, _ChatTab):
                continue
            for bubble, _entry in tab.links:
                if bubble.text():
                    bubble.set_text(bubble.text())

    def _apply_icon_colors(self):
        """Recolour all Tabler icons to match the active theme."""
        colors = theme_colors(self.config.get("appearance", "theme", "dark"))
        muted, accent = colors["muted"], colors["accent"]
        close_button = colors.get("close_button", "#FF5C5C")
        white = colors.get("user_message_text", "#FFFFFF")
        self.logo_label.setPixmap(
            create_icon("sparkles", 20, accent, 1.8).pixmap(20, 20))
        for btn in (self.new_chat_btn, self.settings_btn, self.close_btn,
                    self.attach_btn):
            if isinstance(btn, IconButton):
                btn.set_color(muted)
        if isinstance(self.web_search_btn, IconButton):
            self.web_search_btn.set_colors(muted, accent)
        self._update_send_button()
        self._update_mic_button()
        self.web_banner_icon.setPixmap(
            create_icon("world-search", 14, muted, 1.6).pixmap(14, 14))
        for i in range(self.tabs_widget.count()):
            button = self._tab_close_button(i)
            if isinstance(button, IconButton):
                button.set_color(close_button)
                button.set_hover_color(white)

    def _update_send_button(self):
        """Switch the send button between Send (arrow-up) and Stop (square)."""
        colors = theme_colors(self.config.get("appearance", "theme", "dark"))
        white = colors.get("user_message_text", "#FFFFFF")
        if self._current_task() is not None:
            icon = create_icon("square", 18, white, 2.0, filled=True,
                               disabled_color="#B9B9C4")
            self.send_btn.setToolTip(t("chat.stop_tooltip"))
            self.send_btn.setProperty("stop", True)
        else:
            icon = create_icon("arrow-up", 20, white, 2.2,
                               disabled_color="#B9B9C4")
            self.send_btn.setToolTip(t("chat.send_tooltip"))
            self.send_btn.setProperty("stop", False)
        self.send_btn.setIcon(icon)
        self.send_btn.style().unpolish(self.send_btn)
        self.send_btn.style().polish(self.send_btn)

    def _retranslate(self):
        """Re-apply all user-facing strings for the current language."""
        self.new_chat_btn.setToolTip(t("chat.new_tab_tooltip"))
        self.settings_btn.setToolTip(t("chat.settings_tooltip"))
        self.close_btn.setToolTip(t("chat.close_tooltip"))
        self.web_search_btn.setToolTip(t("chat.web_search_tooltip"))
        self.attach_btn.setToolTip(t("chat.attach_tooltip"))
        self.input.setPlaceholderText(t("chat.input_placeholder"))
        self.hint_label.setText(t("chat.hint"))
        self._renumber_tabs()
        self._update_send_button()
        self._update_mic_button()
        if self.stt_status_row.isVisible():
            self.stt_status.setText(t("stt.listening"))

    def _target_opacity(self) -> float:
        value = float(self.config.get("appearance", "opacity", 0.92))
        return max(0.5, min(1.0, value))

    def _animations_enabled(self) -> bool:
        return bool(self.config.get("appearance", "animations", True))

    def apply_config_changes(self):
        self._apply_config()
        self._retranslate()
        self.web_search_btn.setChecked(self._web_search_enabled())
        self._update_composer_lock()

    # ----------------------------------------------------------------- tabs

    def _current_tab(self) -> _ChatTab:
        tab = self.tabs_widget.currentWidget()
        if isinstance(tab, _ChatTab):
            return tab
        return None

    def _tab_busy(self, tab) -> bool:
        return any(task.tab is tab for task in self._tasks.values())

    def _current_task(self):
        """The task running in the CURRENT tab, if any."""
        tab = self._current_tab()
        if tab is None:
            return None
        for task in self._tasks.values():
            if task.tab is tab:
                return task
        return None

    def _update_composer_lock(self):
        """Lock the shared composer while the current tab is generating."""
        busy = self._current_task() is not None
        self.input.setReadOnly(busy)
        self.attach_btn.setEnabled(not busy)
        self.web_search_btn.setEnabled(not busy)
        self.mic_btn.setEnabled(not busy and self._stt_enabled())

    def _renumber_tabs(self):
        for i in range(self.tabs_widget.count()):
            self.tabs_widget.setTabText(i, t("chat.tab_title", n=i + 1))

    def _add_tab(self) -> _ChatTab:
        tab = _ChatTab()
        index = self.tabs_widget.addTab(tab, t("chat.tab_title", n=self.tabs_widget.count() + 1))
        self._setup_tab_close_button(index, tab)
        self.tabs_widget.setCurrentIndex(index)
        self._renumber_tabs()
        return tab

    def _setup_tab_close_button(self, index: int, tab: _ChatTab):
        """Place a red close button inside the tab and bind it to this tab.

        The button is wrapped so it sits ~4px left of the tab's right edge
        (QSS margins do not reposition QTabBar tab buttons).
        """
        from PySide6.QtWidgets import QTabBar
        colors = theme_colors(self.config.get("appearance", "theme", "dark"))
        close_button = colors.get("close_button", "#FF5C5C")
        white = colors.get("user_message_text", "#FFFFFF")
        close_btn = IconButton("x", tooltip=t("chat.close_tab_tooltip"), size=11,
                               color=close_button)
        close_btn.setObjectName("tab_close_btn")
        close_btn.setFixedSize(18, 18)
        close_btn.set_hover_color(white)
        close_btn.clicked.connect(
            lambda checked=False, t=tab: self._close_tab(self.tabs_widget.indexOf(t)))
        wrapper = QWidget()
        wrapper_lay = QHBoxLayout(wrapper)
        wrapper_lay.setContentsMargins(0, 0, 4, 0)
        wrapper_lay.addWidget(close_btn)
        wrapper.setCursor(Qt.PointingHandCursor)
        self.tabs_widget.tabBar().setTabButton(index, QTabBar.RightSide, wrapper)

    def _tab_close_button(self, index: int):
        """Return the IconButton used to close the tab at ``index`` (if any)."""
        widget = self.tabs_widget.tabBar().tabButton(index, QTabBar.RightSide)
        if isinstance(widget, IconButton):
            return widget
        if widget is not None:
            for child in widget.findChildren(IconButton):
                return child
        return None

    def _close_tab(self, index: int):
        target = self.tabs_widget.widget(index)
        if isinstance(target, _ChatTab) and self._tab_busy(target):
            return  # a generating tab cannot be closed
        if self.tabs_widget.count() <= 1:
            # Reset the last remaining tab instead of closing it.
            tab = self.tabs_widget.widget(0)
            if isinstance(tab, _ChatTab):
                self._clear_tab_content(tab)
            self._save_history()
            self._update_send_state()
            return
        self.tabs_widget.removeTab(index)
        self._renumber_tabs()
        self._save_history()
        self._update_send_state()

    def _on_tab_changed(self, index: int):
        self._update_send_state()
        self._update_send_button()
        self._update_composer_lock()
        if self._animations_enabled():
            tab = self._current_tab()
            if tab is not None:
                animate_fade_slide_in(tab.scroll, 190, dy=8)

    def _clear_tab_content(self, tab: _ChatTab):
        tab.conversation = []
        tab.links = []
        tab._pending_vision_bubble = None
        tab._assistant_bubble = None
        while tab.messages_layout.count() > 1:
            item = tab.messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if tab._thinking is not None:
            tab._thinking.stop()
            tab._thinking = None
            tab._thinking_container = None
        self._clear_image()

    # -------------------------------------------------------------- history

    def _load_history(self):
        if not self.config.get("general", "remember_history", False):
            return
        path = history_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        tabs_data = data.get("tabs")
        if not tabs_data and data.get("conversation"):
            tabs_data = [{
                "conversation": data.get("conversation", []),
                "display": data.get("display", []),
            }]
        if not tabs_data:
            return
        # Remove the placeholder tab created at init.
        while self.tabs_widget.count():
            self.tabs_widget.removeTab(0)
        for tab_data in tabs_data:
            tab = _ChatTab()
            self.tabs_widget.addTab(tab, "")
            tab.conversation = [dict(m) for m in tab_data.get("conversation", [])]
            shown = []
            for entry in tab_data.get("display", []):
                role = entry.get("role")
                text = entry.get("text", "")
                has_image = entry.get("has_image", False)
                if role == "user":
                    shown.append(self._add_user_bubble(
                        text, has_image=has_image, tab=tab))
                elif role == "assistant":
                    shown.append(self._add_assistant_bubble(
                        text, streaming=False, tab=tab))
            # Display entries mirror the user/assistant conversation 1:1.
            conv_entries = [e for e in tab.conversation
                            if e.get("role") in ("user", "assistant")]
            for bubble, entry in zip(shown, conv_entries):
                if bubble.sender == entry.get("role"):
                    self._link_bubble(tab, bubble, entry)
            self._setup_tab_close_button(self.tabs_widget.count() - 1, tab)
        self._renumber_tabs()
        self.tabs_widget.setCurrentIndex(0)

    @staticmethod
    def _history_text(content) -> str:
        """Plain-text form of a message content (list content keeps its text parts)."""
        if isinstance(content, list):
            return "\n".join(
                part.get("text", "") for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ).strip()
        return content or ""

    def _save_history(self):
        if not self.config.get("general", "remember_history", False):
            return
        try:
            tabs_data = []
            for i in range(self.tabs_widget.count()):
                tab = self.tabs_widget.widget(i)
                if not isinstance(tab, _ChatTab):
                    continue
                # Direct-image entries carry base64 content parts; persist
                # only their text so history.json stays small and loadable.
                # File messages keep the full text for the model context but
                # show the short "_display" variant.
                conversation = []
                for message in tab.conversation:
                    saved = dict(message)
                    if isinstance(saved.get("content"), list):
                        saved["content"] = self._history_text(saved["content"])
                    conversation.append(saved)
                display = []
                for message in conversation:
                    if message["role"] in ("user", "assistant"):
                        display.append({
                            "role": message["role"],
                            "text": message.get("_display") or message["content"],
                            "has_image": message.get("_image", False),
                        })
                tabs_data.append({"conversation": conversation, "display": display})
            history_path().write_text(
                json.dumps({"tabs": tabs_data}, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            pass

    def start_new_chat(self):
        self._add_tab()
        self._save_history()
        self._update_send_state()

    # -------------------------------------------------------------- bubbles

    def _bubble_max_width(self) -> int:
        return max(200, int(self.width() * 0.78))

    def _add_message_widget(self, widget, tab=None):
        tab = tab or self._current_tab()
        if tab is None:
            return
        tab.messages_layout.insertWidget(tab.messages_layout.count() - 1, widget)
        if self._animations_enabled() and widget.isVisible():
            animate_fade_in(widget, 190)
        self._scroll_to_bottom(tab)

    def _scroll_to_bottom(self, tab=None):
        tab = tab or self._current_tab()
        if tab is None:
            return
        bar = tab.scroll.verticalScrollBar()
        if self._animations_enabled():
            QTimer.singleShot(0, lambda: smooth_scroll(bar, bar.maximum()))
        else:
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def _scaled_bubble_pixmap(self, pixmap: QPixmap) -> QPixmap:
        max_w = min(220, self._bubble_max_width() - 30)
        return pixmap.scaled(max_w, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _link_bubble(self, tab, bubble, entry):
        """Bind a bubble to its conversation entry (for edit/delete)."""
        tab.links.append((bubble, entry))

    def _wire_bubble_menu(self, bubble, allow_edit: bool, tab):
        bubble.tab = tab or self._current_tab()
        bubble.set_modify_check(
            lambda tab=bubble.tab: not self._tab_busy(tab))
        if allow_edit:
            bubble.set_edit_check(lambda b=bubble: self._edit_allowed(b))
        bubble.menu_delete = True
        bubble.actionRequested.connect(
            lambda action, b=bubble: self._on_bubble_action(b, action))

    def _edit_allowed(self, bubble) -> bool:
        """Editing is only offered for the last user message of an idle tab."""
        tab = getattr(bubble, "tab", None)
        if tab is None or self._tab_busy(tab):
            return False
        if not tab.links or tab.links[-1][0] is not bubble:
            return False
        entry = tab.links[-1][1]
        return (entry.get("role") == "user"
                and not entry.get("_image")
                and not entry.get("_files"))

    def _add_user_bubble(self, text: str, has_image: bool = False,
                         pixmap: QPixmap = None, name: str = "", tab=None):
        bubble = Bubble("user", self._bubble_max_width())
        self._wire_bubble_menu(bubble, allow_edit=True, tab=tab)
        muted = theme_colors(self.config.get("appearance", "theme", "dark"))["muted"]
        photo = inline_icon_img("photo", muted, 15, 1.6)
        image_word = t("chat.image_name")
        if pixmap is not None:
            bubble.set_image(self._scaled_bubble_pixmap(pixmap))
            if text:
                bubble.set_text(text)
            elif name:
                bubble.set_html(f'<span style="opacity:0.85;">{photo} {html.escape(name)}</span>')
            else:
                bubble.set_html(f'<span style="opacity:0.85;">{photo} {image_word}</span>')
        elif has_image:
            bubble.set_html(f'<span style="opacity:0.85;">{photo} {image_word}</span>')
            if text:
                bubble.set_text(text)
        else:
            bubble.set_text(text or "")
        wrapper = QHBoxLayout()
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addStretch(1)
        wrapper.addWidget(bubble)
        container = QWidget()
        container.setLayout(wrapper)
        bubble.container = container
        self._add_message_widget(container, tab)
        return bubble

    def _add_assistant_bubble(self, text: str, streaming: bool = False, tab=None):
        bubble = Bubble("assistant", self._bubble_max_width())
        self._wire_bubble_menu(bubble, allow_edit=False, tab=tab)
        bubble.set_text(text or "")
        wrapper = QHBoxLayout()
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(bubble)
        wrapper.addStretch(1)
        container = QWidget()
        container.setLayout(wrapper)
        bubble.container = container
        self._add_message_widget(container, tab)
        return bubble

    # ------------------------------------------------- message context actions

    def _on_bubble_action(self, bubble, action: str):
        if action == "copy":
            text = bubble.text() or re.sub(
                r"<[^>]+>", "", bubble.label.text()).strip()
            if text:
                QApplication.clipboard().setText(text)
            return
        tab = getattr(bubble, "tab", None) or self._current_tab()
        if tab is None or self._tab_busy(tab):
            return
        link = next((ln for ln in tab.links if ln[0] is bubble), None)
        if link is None:
            return
        _, entry = link
        if action == "delete":
            self._remove_linked_message(tab, link)
            self._save_history()
        elif action == "edit" and self._edit_allowed(bubble):
            current = entry.get("content", "")
            new_text = self._edit_message_dialog(current)
            if new_text is None:
                return
            new_text = new_text.strip()
            if not new_text or new_text == current:
                return
            entry["content"] = new_text
            bubble.set_text(new_text)
            # Drop the stale AI reply that followed, if any.
            index = tab.links.index(link)
            if (index + 1 < len(tab.links)
                    and tab.links[index + 1][1].get("role") == "assistant"):
                self._remove_linked_message(tab, tab.links[index + 1])
            self._save_history()
            # Ask the AI to answer the edited message.
            self._start_text_task(tab, new_text,
                                  web_search=self._web_search_enabled())

    def _remove_linked_message(self, tab, link):
        bubble, entry = link
        if entry in tab.conversation:
            tab.conversation.remove(entry)
        if link in tab.links:
            tab.links.remove(link)
        container = getattr(bubble, "container", None)
        if container is not None:
            container.deleteLater()
        else:
            bubble.deleteLater()

    def _edit_message_dialog(self, text: str):
        """Modal editor for a sent user message. Returns new text or None."""
        dialog = QDialog(self)
        dialog.setWindowTitle(t("chat.edit_title"))
        dialog.setModal(True)
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        editor = QPlainTextEdit()
        editor.setObjectName("memory_field")
        editor.setPlainText(text)
        editor.setMinimumSize(380, 150)
        lay.addWidget(editor)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton(t("common.cancel"))
        cancel_btn.setObjectName("ghost")
        cancel_btn.clicked.connect(dialog.reject)
        save_btn = QPushButton(t("common.save"))
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(dialog.accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        lay.addLayout(buttons)
        if dialog.exec() == QDialog.Accepted:
            return editor.toPlainText()
        return None

    def _show_thinking(self, text: str = None, tab=None):
        tab = tab or self._current_tab()
        if tab is None:
            return
        if tab._thinking is None:
            muted = theme_colors(self.config.get("appearance", "theme", "dark"))["muted"]
            tab._thinking = ThinkingIndicator(self._bubble_max_width(), color=muted)
            wrapper = QHBoxLayout()
            wrapper.setContentsMargins(0, 0, 0, 0)
            wrapper.addWidget(tab._thinking)
            wrapper.addStretch(1)
            tab._thinking_container = QWidget()
            tab._thinking_container.setLayout(wrapper)
            self._add_message_widget(tab._thinking_container, tab)
        tab._thinking.start(text or t("chat.thinking"))
        tab._thinking_container.show()

    def _hide_thinking(self, tab=None):
        tab = tab or self._current_tab()
        if tab is None:
            return
        if tab._thinking is not None:
            tab._thinking.stop()
            if tab._thinking_container is not None:
                tab._thinking_container.hide()
            tab._thinking = None
            tab._thinking_container = None

    def _show_error_bubble(self, message: str, detail: str = "", tab=None):
        bubble = Bubble("error", self._bubble_max_width())
        bubble.set_text(message)
        if detail:
            bubble.add_detail_row(t("chat.tech_details"), detail)
        wrapper = QHBoxLayout()
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(bubble)
        wrapper.addStretch(1)
        container = QWidget()
        container.setLayout(wrapper)
        self._add_message_widget(container, tab)

    def _show_info_bubble(self, message: str, tab=None):
        bubble = Bubble("assistant", self._bubble_max_width())
        bubble.set_text(message)
        wrapper = QHBoxLayout()
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(bubble)
        wrapper.addStretch(1)
        container = QWidget()
        container.setLayout(wrapper)
        self._add_message_widget(container, tab)

    # ------------------------------------------------------------ clipboard

    def _handle_clipboard_paste(self) -> bool:
        mime = QApplication.clipboard().mimeData()
        if mime.hasImage():
            image = QApplication.clipboard().image()
            if not image.isNull():
                self._set_pending_image(image, t("chat.image_clipboard"))
                return True
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if path and Path(path).suffix.lower() in IMAGE_EXTENSIONS:
                    image = QPixmap(path).toImage()
                    if not image.isNull():
                        self._set_pending_image(image, Path(path).name)
                        return True
        return False

    def _set_pending_image(self, image, name: str = ""):
        self.pending_image = image
        self.pending_image_name = name
        self.preview.set_image(QPixmap.fromImage(image), name)
        self.preview.show()
        if self._animations_enabled():
            animate_fade_slide_in(self.preview, 180, dy=-8)
        self._update_send_state()

    def _clear_image(self):
        self.pending_image = None
        self.pending_image_name = ""
        if self._animations_enabled() and self.preview.isVisible():
            animate_fade_out(self.preview, 120, on_hidden=self.preview.hide)
        else:
            self.preview.hide()
        self._update_send_state()

    def _on_attach_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("chat.attach_dialog_title"), "",
            t("chat.filter_images") + ";;" + t("chat.filter_text") + ";;" + t("chat.filter_all"))
        if not path:
            return
        suffix = Path(path).suffix.lower()
        if suffix in IMAGE_EXTENSIONS:
            pixmap = QPixmap(path)
            if pixmap.isNull():
                self._show_error_bubble(t("chat.error_image_load"),
                                        f"File: {path}")
                return
            self._set_pending_image(pixmap.toImage(), Path(path).name)
        elif suffix in DOC_EXTENSIONS:
            self._attach_document(path)
        else:
            self._show_info_bubble(t("chat.file_unsupported"))

    def _attach_document(self, path: str):
        """Read a document's text and pin it as a chip above the composer."""
        try:
            text, _truncated = read_document(path)
        except DocumentError as e:
            self._show_error_bubble(t(e.key, **e.kwargs), e.detail)
            return
        self.pending_docs.append((Path(path).name, text))
        self._refresh_doc_chips()
        self._update_send_state()
        self.input.setFocus()

    def _remove_doc(self, index: int):
        if 0 <= index < len(self.pending_docs):
            self.pending_docs.pop(index)
            self._refresh_doc_chips()
            self._update_send_state()

    def _clear_docs(self):
        self.pending_docs.clear()
        self._refresh_doc_chips()

    def _refresh_doc_chips(self):
        lay = self.doc_chips_row.layout()
        while lay.count():
            item = lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        colors = theme_colors(self.config.get("appearance", "theme", "dark"))
        for index, (name, _text) in enumerate(self.pending_docs):
            chip = QFrame()
            chip.setObjectName("doc_chip")
            chip_lay = QHBoxLayout(chip)
            chip_lay.setContentsMargins(9, 3, 5, 3)
            chip_lay.setSpacing(6)
            icon_label = QLabel()
            icon_label.setPixmap(create_icon("file-text", 13, colors["muted"], 1.6)
                                 .pixmap(13, 13))
            chip_lay.addWidget(icon_label)
            name_label = QLabel(name)
            name_label.setToolTip(name)
            chip_lay.addWidget(name_label)
            remove_btn = IconButton("x", tooltip=t("chat.remove_doc_tooltip"), size=10)
            remove_btn.setFixedSize(16, 16)
            remove_btn.clicked.connect(
                lambda checked=False, i=index: self._remove_doc(i))
            chip_lay.addWidget(remove_btn)
            lay.addWidget(chip)
        lay.addStretch(1)
        self.doc_chips_row.setVisible(bool(self.pending_docs))

    def _compose_docs_message(self, text: str, docs) -> str:
        """Full message sent to the model: user text + file snippets."""
        if not docs:
            return text
        snippets = [t("chat.file_snippet", name=name, content=content)
                    for name, content in docs]
        return (text + "\n\n" if text else "") + "\n".join(snippets)

    @staticmethod
    def _docs_display_text(text: str, docs) -> str:
        """Short variant shown in the bubble: text + attached-file lines."""
        if not docs:
            return text
        lines = [t("chat.file_attached", name=name, count=len(content))
                 for name, content in docs]
        return (text + "\n" if text else "") + "\n".join(lines)

    # ---------------------------------------------------------------- send

    def _system_prompt(self) -> str:
        """Base system prompt plus the user's memory (about me / custom prompt)."""
        extra = ""
        if self.config.get("memory", "enabled", False):
            extra = (self.config.get("memory", "context", "") or "").strip()
        if not extra:
            return SYSTEM_PROMPT
        return (SYSTEM_PROMPT + "\n\n"
                "Информация о пользователе и его персональные инструкции "
                "(учитывай их в каждом ответе):\n" + extra)

    def _update_send_state(self):
        if self._current_task() is not None:
            # During generation the button acts as Stop and stays enabled.
            self.send_btn.setEnabled(True)
        else:
            has_text = bool(self.input.toPlainText().strip())
            enabled = has_text or self.pending_image is not None or bool(self.pending_docs)
            if enabled and not self.send_btn.isEnabled() and self._animations_enabled():
                animate_fade_in(self.send_btn, 150)
            self.send_btn.setEnabled(enabled)

    def _auto_resize_input(self):
        """Keep the input at one line height and grow with multiline text."""
        doc = self.input.document()
        height = int(doc.size().height()) + 20
        min_h = 40
        max_h = 120
        self.input.setFixedHeight(max(min_h, min(max_h, height)))

    def _on_send_or_stop(self):
        if self._current_task() is not None:
            self._stop_generation()
        elif self._stt_dictating:
            # Commit the dictation, then send the resulting message.
            self._stt_send_after = True
            self._stop_dictation()
        else:
            self.send_current()

    def _stop_generation(self):
        """Really interrupt the current tab's task and keep partial text."""
        task = self._current_task()
        if task is None:
            return
        task.cancel_event.set()
        if task.deepseek is not None:
            try:
                task.deepseek.cancel()
            except Exception:
                pass
        # Safety net: if the worker is stuck (e.g. in a non-cancellable call),
        # finalize the UI state shortly.
        if task.watchdog is not None:
            task.watchdog.stop()
        task.watchdog = QTimer(self)
        task.watchdog.setSingleShot(True)
        task.watchdog.setInterval(2500)
        task.watchdog.timeout.connect(
            lambda tid=task.id: self._finalize_after_stop(tid))
        task.watchdog.start()

    def _finalize_after_stop(self, task_id: int):
        if task_id in self._tasks:
            self._on_cancelled(task_id)

    def send_current(self):
        tab = self._current_tab()
        if tab is None or self._tab_busy(tab) or self._stt_dictating:
            return
        text = self.input.toPlainText().strip()
        docs = list(self.pending_docs)  # copy: cleared below before composing
        if not text and self.pending_image is None and not docs:
            return
        image = self.pending_image
        image_name = self.pending_image_name
        self._clear_image()
        self._clear_docs()
        self.input.clear()

        if image is not None:
            # Documents attached together with an image ride along as text.
            full_text = self._compose_docs_message(text, docs)
            display = self._docs_display_text(text, docs)
            pixmap = QPixmap.fromImage(image)
            user_bubble = self._add_user_bubble(
                display, pixmap=pixmap, name=image_name, tab=tab)
            if self._vision_enabled():
                tab._pending_vision_bubble = user_bubble
                self._start_vision_task(tab, image, full_text, image_name)
            else:
                # Cloudflare vision is off — hand the image straight to the
                # main text model (OpenAI-style content parts).
                parts = []
                if full_text:
                    parts.append({"type": "text", "text": full_text})
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": self._image_data_uri(image)},
                })
                entry = {"role": "user", "content": parts, "_image": True}
                if docs:
                    entry["_files"] = [name for name, _ in docs]
                    entry["_display"] = display
                tab.conversation.append(entry)
                self._link_bubble(tab, user_bubble, entry)
                self._start_text_task(tab, full_text, web_search=self._web_search_enabled())
        else:
            # Full content (message + file snippets) goes to the model; the
            # bubble shows the short variant with attached-file lines.
            content = self._compose_docs_message(text, docs)
            display = self._docs_display_text(text, docs)
            entry = {"role": "user", "content": content}
            if docs:
                entry["_files"] = [name for name, _ in docs]
                entry["_display"] = display
            user_bubble = self._add_user_bubble(display, tab=tab)
            tab.conversation.append(entry)
            self._link_bubble(tab, user_bubble, entry)
            self._start_text_task(tab, text or display, web_search=self._web_search_enabled())

    # ------------------------------------------------------------- speech-to-text

    def _stt_enabled(self) -> bool:
        return bool(self.config.get_stt("enabled", False))

    def _update_mic_button(self):
        """Switch the mic button between idle mic and a recording-stop square."""
        colors = theme_colors(self.config.get("appearance", "theme", "dark"))
        muted = colors["muted"]
        white = colors.get("user_message_text", "#FFFFFF")
        if self._stt_dictating:
            self.mic_btn.setIcon(create_icon("square", 14, white, 2.0, filled=True))
            self.mic_btn.setToolTip(t("stt.stop_record"))
            self.mic_btn.setProperty("recording", True)
        else:
            self.mic_btn.setIcon(create_icon("microphone", 16, muted, 1.8))
            self.mic_btn.setToolTip(t("stt.start_dictation"))
            self.mic_btn.setProperty("recording", False)
        self.mic_btn.style().unpolish(self.mic_btn)
        self.mic_btn.style().polish(self.mic_btn)

    def _stt_show_status(self, text: str, error: bool = False):
        self.stt_status.setText(text)
        self.stt_status.setObjectName("status_err" if error else "hint")
        self.stt_status.style().unpolish(self.stt_status)
        self.stt_status.style().polish(self.stt_status)
        colors = theme_colors(self.config.get("appearance", "theme", "dark"))
        icon_color = colors["close_button"] if error else colors["accent"]
        self.stt_status_icon.setPixmap(
            create_icon("microphone", 14, icon_color, 1.8).pixmap(14, 14))
        self.stt_status_row.show()

    def _stt_tick_dots(self):
        self._stt_dots = (self._stt_dots + 1) % 4
        self.stt_status.setText(t("stt.listening") + "." * self._stt_dots)

    def _on_mic_clicked(self):
        if self._stt_dictating:
            self._stop_dictation()
        else:
            self._start_dictation()

    def open_with_dictation(self):
        """Show the chat window and begin dictation (used by the STT hotkey)."""
        if self._stt_dictating:
            self._stop_dictation()
            return
        if not self.isVisible():
            self.position_centered()
            self.show_animated()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
        QTimer.singleShot(0, self._start_dictation)

    def _start_dictation(self):
        if self._stt_active or self._current_task() is not None:
            return
        if not self._stt_enabled():
            self._stt_show_status(t("stt.disabled_in_settings"), error=True)
            return
        model_path = self.config.get_stt("model_path", "")
        if not model_is_valid(model_path):
            self._stt_show_status(t("stt.model_not_found"), error=True)
            return

        mic = self.config.get_stt("microphone", "")
        if mic and not device_exists(mic):
            mic = ""
            self.config.set_stt("microphone", "")
            self.config.save()
            self._show_info_bubble(t("stt.mic_fallback_warning"))
        silence = float(self.config.get_stt(
            "silence_timeout", DEFAULT_STT_SILENCE_TIMEOUT) or DEFAULT_STT_SILENCE_TIMEOUT)

        self._stt_base_text = self.input.toPlainText()
        self._stt_prior_readonly = self.input.isReadOnly()
        self.input.setReadOnly(True)

        thread = QThread(self)
        worker = SpeechWorker(model_path=model_path, microphone=mic,
                              silence_timeout=silence)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.started.connect(self._on_stt_started)
        worker.partial.connect(self._on_stt_partial)
        worker.result.connect(self._on_stt_result)
        worker.finished.connect(self._on_stt_finished)
        worker.error.connect(self._on_stt_error)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)

        self._stt_thread = thread
        self._stt_worker = worker
        self._stt_active = True
        self._stt_dictating = True
        self._stt_send_after = False
        self._stt_error_occurred = False
        self._stt_pending_result = ""
        self._stt_dots = 0
        self._update_mic_button()
        self._stt_show_status(t("stt.starting"))
        if self._animations_enabled():
            animate_fade_in(self.mic_btn, 120)
        thread.start()

    def _stop_dictation(self):
        """Request the worker to finish; the final text lands in the input."""
        if not self._stt_active:
            return
        self._stt_show_status(t("stt.stopping"))
        if self._stt_worker is not None:
            try:
                self._stt_worker.stop()
            except Exception:
                pass

    def _set_input_stt(self, text: str):
        base = self._stt_base_text
        if text:
            combined = (base + " " + text) if (base and not base.endswith((" ", "\n"))) else (base + text)
        else:
            combined = base
        self.input.setPlainText(combined)
        self.input.moveCursor(QTextCursor.End)

    def _end_stt_session(self, keep_status: bool = False):
        if not self._stt_active:
            return
        self._stt_active = False
        self._stt_dictating = False
        if self._stt_dots_timer is not None:
            self._stt_dots_timer.stop()
        self.input.setReadOnly(self._stt_prior_readonly)
        self._update_mic_button()
        if self._animations_enabled():
            animate_fade_in(self.mic_btn, 120)
        if not keep_status:
            self.stt_status_row.hide()
        self._stt_cleanup_thread()
        if self._stt_send_after:
            self._stt_send_after = False
            QTimer.singleShot(0, self.send_current)

    def _stt_cleanup_thread(self):
        thread = self._stt_thread
        self._stt_thread = None
        self._stt_worker = None
        if thread is not None and thread.isRunning():
            thread.quit()

    def _on_stt_started(self):
        if not self._stt_active:
            return
        self._stt_dots = 0
        self._stt_show_status(t("stt.listening"))
        if self._stt_dots_timer is not None:
            self._stt_dots_timer.start()

    def _on_stt_partial(self, text: str):
        if not self._stt_active or self._stt_error_occurred:
            return
        self._set_input_stt(text)

    def _on_stt_result(self, text: str):
        if not self._stt_active or self._stt_error_occurred:
            return
        self._stt_pending_result = text
        self._set_input_stt(text)

    def _on_stt_finished(self):
        if self._stt_error_occurred:
            self._stt_error_occurred = False
            return
        self._end_stt_session(keep_status=False)

    def _on_stt_error(self, message: str, detail: str):
        self._stt_error_occurred = True
        self._stt_show_status(message, error=True)
        if detail:
            self.stt_status.setToolTip(detail)
        self._end_stt_session(keep_status=True)

    def shutdown(self):
        """Stop any active dictation and release audio resources."""
        if self._stt_active:
            if self._stt_worker is not None:
                try:
                    self._stt_worker.stop()
                except Exception:
                    pass
            self._end_stt_session(keep_status=False)

    # -------------------------------------------------------------- workers

    def _make_deepseek(self, task: _TaskState = None) -> DeepSeekClient:
        client = DeepSeekClient(
            api_url=self.config.get("deepseek", "api_url", DEFAULT_APP_URL),
            api_key=self.config.get_deepseek_key(),
            model=self.config.get("deepseek", "model", DEFAULT_MODEL),
        )
        if task is not None:
            task.deepseek = client  # lets Stop() abort this task's stream
        return client

    def _make_vision(self) -> CloudflareVisionClient:
        return CloudflareVisionClient(
            account_id=self.config.get("vision", "account_id", ""),
            api_token=self.config.get_vision_token(),
            model=self.config.get("vision", "model", DEFAULT_VISION_MODEL),
        )

    def _vision_enabled(self) -> bool:
        return bool(self.config.get("vision", "enabled", True))

    @staticmethod
    def _image_data_uri(image) -> str:
        """Encode a QImage as a PNG data-URI for OpenAI-style image content."""
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        image.save(buf, "PNG")
        buf.close()
        return "data:image/png;base64," + base64.b64encode(bytes(ba)).decode("ascii")

    def _web_search_enabled(self) -> bool:
        return bool(self.config.get("web_search", "enabled", False))

    def _toggle_web_search(self, checked: bool):
        self.config.set("web_search", "enabled", bool(checked))
        self.config.save()

    def _make_websearch(self) -> WebSearchClient:
        return WebSearchClient(
            provider=self.config.get("web_search", "provider", DEFAULT_WEBSEARCH_PROVIDER),
            api_url=self.config.get("web_search", "api_url", DEFAULT_WEBSEARCH_URL),
            api_key=self.config.get_websearch_key(),
            max_results=int(self.config.get("web_search", "max_results", 5) or 5),
            timeout=int(self.config.get("web_search", "timeout", 15) or 15),
        )

    def _show_web_banner(self, text: str):
        self.web_banner_text.setText(text)
        self.web_banner.show()
        if self._animations_enabled():
            animate_fade_slide_in(self.web_banner, 170, dy=-6)

    def _hide_web_banner(self):
        if self._animations_enabled() and self.web_banner.isVisible():
            animate_fade_out(self.web_banner, 120, on_hidden=self.web_banner.hide)
        else:
            self.web_banner.hide()

    def _start_text_task(self, tab: _ChatTab, question: str, web_search: bool = False):
        self._task_id += 1
        task = _TaskState(self._task_id, tab)
        self._tasks[task.id] = task
        cancel_event = task.cancel_event
        if web_search:
            self._show_thinking(t("chat.thinking_decision"), tab)
        else:
            self._show_thinking(t("chat.thinking"), tab)
        messages = ([{"role": "system", "content": self._system_prompt()}]
                    + list(tab.conversation))
        if tab is self._current_tab():
            self._update_send_state()
            self._update_send_button()
            self._update_composer_lock()

        def cancelled():
            return cancel_event.is_set()

        def generator():
            deepseek = self._make_deepseek(task)

            def stream(msgs):
                try:
                    for chunk in deepseek.stream_message(msgs, cancel_event=cancel_event):
                        if cancelled():
                            raise GenerationCancelled()
                        yield ("chunk", chunk)
                except GenerationCancelled:
                    yield ("cancelled",)
                except APIError as e:
                    yield ("error", e.message, e.detail)

            if not web_search:
                for item in stream(messages):
                    yield item
                return

            # Step 1 — DeepSeek decides whether fresh web data is needed.
            decision_messages = [
                {"role": "system", "content": SEARCH_DECISION_SYSTEM},
                {"role": "user", "content": question},
            ]
            try:
                decision = deepseek.send_message(decision_messages, timeout=30.0)
            except APIError as e:
                yield ("info", t("chat.search_failed_decision", msg=e.message))
                for item in stream(messages):
                    yield item
                return
            if cancelled():
                yield ("cancelled",)
                return
            needs_search, query = _parse_search_decision(decision)

            if not needs_search:
                yield ("status", t("chat.thinking_no_search"))
                for item in stream(messages):
                    yield item
                return

            # Step 2 — real web search.
            yield ("status", t("chat.thinking_searching"))
            yield ("webstatus", t("chat.web_searching"))
            try:
                results = self._make_websearch().search(query or question)
            except APIError as e:
                yield ("info", t("chat.search_failed", msg=e.message))
                for item in stream(messages):
                    yield item
                return
            if cancelled():
                yield ("cancelled",)
                return

            if not results:
                yield ("info", t("chat.search_no_results"))
                yield ("webstatus", t("chat.web_no_results"))
            else:
                yield ("sources", results)
                yield ("webstatus", t("chat.web_found", count=len(results)))

            # Step 3 — DeepSeek answers using the search context.
            yield ("status", t("chat.thinking_answer"))
            context = build_search_context(query or question, results)
            enriched = messages + [{"role": "user", "content": context}]
            for item in stream(enriched):
                yield item

        self._run_generator(generator(), task)

    def _start_vision_task(self, tab: _ChatTab, image, question: str, image_name: str):
        self._task_id += 1
        task = _TaskState(self._task_id, tab)
        self._tasks[task.id] = task
        cancel_event = task.cancel_event
        self._show_thinking(t("chat.thinking_image"), tab)
        if tab is self._current_tab():
            self._update_send_state()
            self._update_send_button()
            self._update_composer_lock()
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        image.save(buf, "PNG")
        buf.close()
        image_bytes = bytes(ba)

        def generator():
            deepseek = self._make_deepseek(task)
            vision = self._make_vision()
            try:
                description = vision.analyze_image_bytes(
                    image_bytes, build_vision_prompt(question))
            except APIError as e:
                yield ("error", e.message, e.detail)
                return
            if cancel_event.is_set():
                yield ("cancelled",)
                return
            user_content = build_deepseek_image_message(description, question)
            yield ("status", t("chat.thinking_answer"))
            messages = ([{"role": "system", "content": self._system_prompt()}]
                        + list(tab.conversation)
                        + [{"role": "user", "content": user_content}])
            try:
                for chunk in deepseek.stream_message(messages, cancel_event=cancel_event):
                    if cancel_event.is_set():
                        raise GenerationCancelled()
                    yield ("chunk", chunk)
            except GenerationCancelled:
                yield ("cancelled",)
                return
            except APIError as e:
                yield ("error", e.message, e.detail)
                return
            # The enriched vision entry is appended from the main thread
            # (see _on_vision_entry) so the bubble link stays consistent.
            yield ("vuser", user_content)

        self._run_generator(generator(), task)

    def _run_generator(self, generator, task: _TaskState):
        thread = QThread(self)
        worker = _GeneratorWorker(generator, task_id=task.id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.status.connect(self._on_status)
        worker.info.connect(self._on_info)
        worker.webstatus.connect(self._on_webstatus)
        worker.sources.connect(self._on_sources)
        worker.chunk.connect(self._on_chunk)
        worker.vision_entry.connect(self._on_vision_entry)
        worker.cancelled.connect(self._on_cancelled)
        worker.done.connect(self._on_done)
        worker.error.connect(self._on_error)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)
        task.thread = thread
        task.worker = worker
        thread.start()

    def _on_status(self, task_id: int, text: str):
        task = self._tasks.get(task_id)
        if task is None:
            return
        if task.tab._thinking is not None:
            task.tab._thinking.set_status(text)

    def _on_info(self, task_id: int, text: str):
        task = self._tasks.get(task_id)
        if task is None:
            return
        self._show_info_bubble(text, task.tab)

    def _on_webstatus(self, task_id: int, text: str):
        task = self._tasks.get(task_id)
        # The single banner only reports on the tab the user is looking at.
        if task is None or task.tab is not self._current_tab():
            return
        self._show_web_banner(text)

    def _on_sources(self, task_id: int, sources):
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.sources = sources

    def _on_vision_entry(self, task_id: int, user_content: str):
        """Append the enriched vision user entry and link it to its bubble."""
        task = self._tasks.get(task_id)
        if task is None:
            return
        tab = task.tab
        entry = {"role": "user", "content": user_content, "_image": True}
        tab.conversation.append(entry)
        bubble = getattr(tab, "_pending_vision_bubble", None)
        if bubble is not None:
            self._link_bubble(tab, bubble, entry)
            tab._pending_vision_bubble = None

    def _on_chunk(self, task_id: int, chunk: str):
        task = self._tasks.get(task_id)
        if task is None:
            return
        tab = task.tab
        if tab._thinking is not None:
            self._hide_thinking(tab)
        if tab._assistant_bubble is None:
            tab._assistant_bubble = self._add_assistant_bubble("", streaming=True, tab=tab)
        tab._assistant_bubble.set_text(tab._assistant_bubble.text() + chunk)
        self._scroll_to_bottom(tab)

    def _on_done(self, task_id: int, full_text: str):
        task = self._tasks.get(task_id)
        if task is None:
            return
        tab = task.tab
        if tab._thinking is not None:
            self._hide_thinking(tab)
        if tab._assistant_bubble is not None:
            if not full_text.strip():
                tab._assistant_bubble.set_text(t("chat.empty_response"))
            else:
                entry = {"role": "assistant", "content": full_text}
                tab.conversation.append(entry)
                self._link_bubble(tab, tab._assistant_bubble, entry)
                if task.sources:
                    colors = theme_colors(
                        self.config.get("appearance", "theme", "dark"))
                    tab._assistant_bubble.add_sources(
                        task.sources, colors["accent"], colors["muted"])
            tab._assistant_bubble = None
        if tab is self._current_tab():
            if task.sources:
                count = len(task.sources)
                self._show_web_banner(t("chat.web_found", count=count))
                QTimer.singleShot(2600, self._hide_web_banner)
            else:
                self._hide_web_banner()
        task.sources = None
        self._finish_worker(task_id)

    def _on_cancelled(self, task_id: int):
        """Generation was stopped by the user — keep the partial answer."""
        task = self._tasks.get(task_id)
        if task is None:
            return
        tab = task.tab
        if tab._thinking is not None:
            self._hide_thinking(tab)
        if tab._assistant_bubble is not None:
            partial = tab._assistant_bubble.text()
            if partial and partial.strip():
                entry = {"role": "assistant", "content": partial}
                tab.conversation.append(entry)
                self._link_bubble(tab, tab._assistant_bubble, entry)
            tab._assistant_bubble = None
            self._show_info_bubble(t("chat.stopped"), tab)
        if tab is self._current_tab():
            self._hide_web_banner()
        task.sources = None
        self._finish_worker(task_id)

    def _on_error(self, task_id: int, message: str, detail: str):
        task = self._tasks.get(task_id)
        if task is None:
            return
        tab = task.tab
        if tab._thinking is not None:
            self._hide_thinking(tab)
        if tab._assistant_bubble is not None:
            tab._assistant_bubble = None
        self._show_error_bubble(t("chat.error_generic_title", message=message),
                                detail, tab)
        if tab is self._current_tab():
            self._hide_web_banner()
        task.sources = None
        self._finish_worker(task_id)

    def _finish_worker(self, task_id: int):
        task = self._tasks.pop(task_id, None)
        if task is None:
            return
        if task.watchdog is not None:
            task.watchdog.stop()
            task.watchdog = None
        thread = task.thread
        task.thread = None
        task.worker = None
        if thread is not None and thread.isRunning():
            thread.quit()
        if task.tab is self._current_tab():
            self._update_send_state()
            self._update_send_button()
            self._update_composer_lock()
        self._save_history()

    # ---------------------------------------------------------------- events

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        if obj is self.input and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.composer.setProperty("focused", event.type() == QEvent.FocusIn)
            self.composer.style().unpolish(self.composer)
            self.composer.style().polish(self.composer)
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            key = event.key()
            mods = event.modifiers()
            if key in (Qt.Key_Return, Qt.Key_Enter) and not (mods & Qt.ShiftModifier):
                self.send_current()
                return True
            if key == Qt.Key_Escape:
                if self.pending_image is not None:
                    self._clear_image()
                    return True
                self.hide_animated()
                return True
            if key == Qt.Key_V and (mods & Qt.ControlModifier):
                if self._handle_clipboard_paste():
                    return True
        return super().eventFilter(obj, event)

    def _on_close_clicked(self):
        # Always hide to tray; the app keeps running in the background.
        self.hide_animated()

    # -------------------------------------------------------------- show/hide

    def position_centered(self, screen=None):
        if screen is None:
            from PySide6.QtGui import QCursor
            cursor = QCursor.pos()
            screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + (geo.height() - self.height()) // 2
        self.move(max(geo.x(), x), max(geo.y(), y))

    def show_animated(self):
        if self._animations_enabled():
            self.setWindowOpacity(0.0)
            self.show()
            self.raise_()
            self.activateWindow()
            self._animate_open()
        else:
            self.setWindowOpacity(self._target_opacity())
            self.show()
            self.raise_()
            self.activateWindow()
        self.input.setFocus()

    def hide_animated(self):
        if self._animations_enabled() and self.isVisible():
            resting = self._resting_geometry()
            center = resting.center()
            end_w = int(resting.width() * 0.96)
            end_h = int(resting.height() * 0.96)
            end_geo = QRect(center.x() - end_w // 2, center.y() - end_h // 2, end_w, end_h)
            self._scale_to(resting, end_geo, 130)
            self._stop_opacity_anim()
            anim_op = QPropertyAnimation(self, b"windowOpacity", self)
            anim_op.setDuration(130)
            anim_op.setStartValue(self.windowOpacity())
            anim_op.setEndValue(0.0)
            anim_op.setEasingCurve(QEasingCurve.InCubic)
            anim_op.finished.connect(self._on_hide_anim_finished)
            anim_op.start()
            self._anim = anim_op
        else:
            self.hide()

    def _animate_open(self):
        """Opacity 0 -> 1 with a gentle 0.96 -> 1 scale, anchored to the center.

        Both geometry keyframes derive from the resting (full-size) geometry,
        so rapid open/hide toggling can never compound into a shrink.
        """
        target = self._resting_geometry()
        center = target.center()
        start_w = int(target.width() * 0.96)
        start_h = int(target.height() * 0.96)
        start_geo = QRect(center.x() - start_w // 2, center.y() - start_h // 2, start_w, start_h)
        self._scale_to(start_geo, target, 170)
        self._stop_opacity_anim()
        anim_op = QPropertyAnimation(self, b"windowOpacity", self)
        anim_op.setDuration(170)
        anim_op.setStartValue(0.0)
        anim_op.setEndValue(self._target_opacity())
        anim_op.setEasingCurve(QEasingCurve.OutCubic)
        anim_op.start()
        self._anim = anim_op

    def _stop_opacity_anim(self):
        """Stop the opacity animation without firing its finished slot —
        QAbstractAnimation.stop() emits finished(), which would run the
        stale hide() right after a fresh show()."""
        if self._anim is not None:
            self._anim.blockSignals(True)
            self._anim.stop()
            self._anim.blockSignals(False)
            self._anim = None

    def _on_hide_anim_finished(self):
        self.hide()
        # Park the hidden window at its full-size geometry one cycle later:
        # the scale animation's last write reaches the QWindow asynchronously
        # and would overwrite a synchronous reset with the shrunk frame.
        QTimer.singleShot(0, self._park_hidden_geometry)

    def _park_hidden_geometry(self):
        if not self.isVisible():
            self.setGeometry(self._resting_geometry())

    # ------------------------------------------------------- scale animations

    def _resting_geometry(self) -> QRect:
        """The window's true full-size geometry, ignoring any scale animation."""
        return self._rest_geo if self._rest_geo is not None else self.geometry()

    def _geo_anim_active(self) -> bool:
        return (self._geo_anim_lock
                or (self._geo_anim is not None
                    and self._geo_anim.state() == QPropertyAnimation.Running))

    def _scale_to(self, start_geo: QRect, end_geo: QRect, duration: int):
        """Animate the window geometry; replaces any animation in flight."""
        if self._geo_anim is not None:
            self._geo_anim.stop()
        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(duration)
        anim.setStartValue(start_geo)
        anim.setEndValue(end_geo)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        self._geo_anim = anim
        self._geo_anim_lock = True
        try:
            # Jump to the start frame before the first tick (kept out of
            # _rest_geo by the lock).
            self.setGeometry(start_geo)
            anim.start()
        finally:
            self._geo_anim_lock = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._geo_anim_active():
            geo = self.geometry()
            self._rest_geo = geo
            # Keep the configured size in sync with manual (edge) resizes;
            # it only reaches disk on the next regular config save.
            self.config.set_window("width", geo.width())
            self.config.set_window("height", geo.height())

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self._geo_anim_active():
            self._rest_geo = self.geometry()

    def nativeEvent(self, eventType, message):
        if eventType == "windows_generic_MSG":
            try:
                msg = wintypes.MSG.from_address(int(message))
            except Exception:
                return super().nativeEvent(eventType, message)
            if msg.message == WM_NCHITTEST:
                # Screen coordinates may be negative on multi-monitor setups.
                x = ctypes.c_short(msg.lParam & 0xFFFF).value
                y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                hit = self._edge_hit(self.mapFromGlobal(QPoint(x, y)))
                if hit:
                    return True, hit
        return super().nativeEvent(eventType, message)

    def _edge_hit(self, pos) -> int:
        """Return the HT* border code when the point is on a resize edge, else 0."""
        margin = RESIZE_MARGIN
        left = pos.x() < margin
        right = pos.x() >= self.width() - margin
        top = pos.y() < margin
        bottom = pos.y() >= self.height() - margin
        if top and left:
            return HTTOPLEFT
        if top and right:
            return HTTOPRIGHT
        if bottom and left:
            return HTBOTTOMLEFT
        if bottom and right:
            return HTBOTTOMRIGHT
        if left:
            return HTLEFT
        if right:
            return HTRIGHT
        if top:
            return HTTOP
        if bottom:
            return HTBOTTOM
        return 0

    def closeEvent(self, event):
        self._save_history()
        if not self._quitting:
            # Never actually close — minimize to tray instead.
            event.ignore()
            self.hide_animated()
            return
        super().closeEvent(event)


class _GeneratorWorker(QObject):
    status = Signal(int, str)
    info = Signal(int, str)
    webstatus = Signal(int, str)
    sources = Signal(int, object)
    chunk = Signal(int, str)
    cancelled = Signal(int)
    done = Signal(int, str)
    error = Signal(int, str, str)
    vision_entry = Signal(int, str)

    def __init__(self, generator, task_id: int = 0, parent=None):
        super().__init__(parent)
        self._generator = generator
        self._task_id = task_id

    def run(self):
        try:
            tid = self._task_id
            acc = []
            for item in self._generator:
                kind = item[0]
                if kind == "status":
                    self.status.emit(tid, item[1])
                elif kind == "info":
                    self.info.emit(tid, item[1])
                elif kind == "webstatus":
                    self.webstatus.emit(tid, item[1])
                elif kind == "sources":
                    self.sources.emit(tid, item[1])
                elif kind == "chunk":
                    acc.append(item[1])
                    self.chunk.emit(tid, item[1])
                elif kind == "vuser":
                    self.vision_entry.emit(tid, item[1])
                elif kind == "cancelled":
                    self.cancelled.emit(tid)
                    return
                elif kind == "error":
                    self.error.emit(tid, item[1], item[2])
                    return
            self.done.emit(tid, "".join(acc))
        except Exception as e:
            self.error.emit(self._task_id, t("chat.unexpected_error", e=e),
                            traceback.format_exc())
