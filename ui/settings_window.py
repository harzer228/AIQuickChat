"""Frameless settings window with a sidebar and animated pages."""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QKeyEvent,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from api.deepseek import DeepSeekClient
from api.vision import CloudflareVisionClient
from api.web_search import PROVIDER_LABELS, PROVIDER_URLS, WebSearchClient
from config import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_APP_URL,
    DEFAULT_MODEL,
    DEFAULT_STT_HOTKEY,
    DEFAULT_STT_SILENCE_TIMEOUT,
    DEFAULT_VISION_MODEL,
    DEFAULT_WEBSEARCH_MAX_RESULTS,
    DEFAULT_WEBSEARCH_PROVIDER,
    DEFAULT_WEBSEARCH_TIMEOUT,
    DEFAULT_WEBSEARCH_URL,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    WINDOW_MAX_HEIGHT,
    WINDOW_MAX_WIDTH,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from stt.engine import list_microphones, model_is_valid
from ui.icons import IconButton, create_icon
from ui.widgets import (
    THEMES as THEME_PALETTES,
)
from ui.widgets import (
    DragHandle,
    animate_fade_in,
    animate_fade_slide_in,
    make_stylesheet,
    run_async,
    theme_colors,
)
from utils.config_manager import ConfigManager, is_start_with_windows, set_start_with_windows
from utils.hotkey import humanize_combo
from utils.i18n import detect_system_language, set_language, t

THEME_CHOICES = [
    ("dark", "Dark"),
    ("light", "Light"),
    ("nord", "Nord"),
    ("dracula", "Dracula"),
    ("solarized", "Solarized Light"),
    ("rose-pine", "Rosé Pine"),
    ("catppuccin", "Catppuccin Mocha"),
    ("tokyo-night", "Tokyo Night"),
    ("everforest", "Everforest"),
    ("gruvbox", "Gruvbox"),
    ("system", "System"),
]

LANGUAGES = [
    ("en", "English"),
    ("ru", "Русский"),
]

WEBSEARCH_PROVIDERS = [
    (key, label) for key, label in PROVIDER_LABELS.items()
]


def _theme_swatch(name: str) -> QPixmap:
    """A small rounded colour swatch for the theme selector."""
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    if name == "system":
        p.setBrush(QColor(THEME_PALETTES["dark"]["accent"]))
        p.drawRoundedRect(1, 4, 8, 10, 3, 3)
        p.setBrush(QColor(THEME_PALETTES["light"]["accent"]))
        p.drawRoundedRect(9, 4, 8, 10, 3, 3)
    else:
        colors = THEME_PALETTES.get(name) or THEME_PALETTES["dark"]
        p.setBrush(QColor(colors["accent"]))
        p.drawRoundedRect(1, 3, 16, 12, 4, 4)
    p.end()
    return pm


class SettingsWindow(QWidget):
    applied = Signal()

    def __init__(self, config: ConfigManager, hotkey_validator=None,
                 stt_hotkey_validator=None):
        super().__init__()
        self.config = config
        self.hotkey_validator = hotkey_validator or (lambda c: (True, None))
        self.stt_hotkey_validator = stt_hotkey_validator or (lambda c: (True, None))
        self._new_hotkey = None
        self._stt_new_hotkey = None
        self._anim = None
        self._text_entries = []  # [(widget, i18n_key), ...] re-applied on language change
        self._section_icons = []  # [(QLabel, icon_name), ...] recolored per theme

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(t("settings.window_title"))

        self._build_ui()
        self._apply_theme()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame()
        self.card.setObjectName("card")
        outer.addWidget(self.card)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(10)

        # header
        header = DragHandle()
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(4, 2, 2, 2)
        header_lay.setSpacing(9)
        self.header_logo = QLabel()
        self.header_logo.setFixedSize(20, 20)
        header_lay.addWidget(self.header_logo)
        self.title_label = self._text_label("title", "settings.title")
        header_lay.addWidget(self.title_label)
        header_lay.addStretch(1)
        self.close_btn = IconButton("x", tooltip=t("common.close"))
        self.close_btn.clicked.connect(self._on_close_clicked)
        header_lay.addWidget(self.close_btn)
        root.addWidget(header)

        header_sep = QFrame()
        header_sep.setObjectName("header_sep")
        header_sep.setFixedHeight(1)
        root.addWidget(header_sep)

        # body: sidebar + stacked pages
        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.stack.setObjectName("settings_stack")
        self.general_page = self._build_general_page()
        self.api_page = self._build_api_page()
        self.stt_page = self._build_stt_page()
        self.stack.addWidget(self.general_page)
        self.stack.addWidget(self.api_page)
        self.stack.addWidget(self.stt_page)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        # footer
        footer = QHBoxLayout()
        footer.setSpacing(8)
        cancel_btn = QPushButton()
        cancel_btn.setObjectName("ghost")
        cancel_btn.clicked.connect(self._on_close_clicked)
        self._text_entries.append((cancel_btn, "common.cancel"))
        self.save_btn = QPushButton()
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self._save)
        self._text_entries.append((self.save_btn, "common.save"))
        footer.addStretch(1)
        footer.addWidget(cancel_btn)
        footer.addWidget(self.save_btn)
        root.addLayout(footer)

        self.general_nav.setChecked(True)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        side_lay = QVBoxLayout(sidebar)
        side_lay.setContentsMargins(10, 12, 10, 12)
        side_lay.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(8)
        self.brand_logo = QLabel()
        self.brand_logo.setFixedSize(22, 22)
        brand_row.addWidget(self.brand_logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand_title = QLabel(APP_NAME)
        brand_title.setObjectName("sidebar_title")
        brand_text.addWidget(brand_title)
        self.sidebar_subtitle = QLabel("")
        self.sidebar_subtitle.setObjectName("sidebar_subtitle")
        brand_text.addWidget(self.sidebar_subtitle)
        brand_row.addLayout(brand_text)
        brand_row.addStretch(1)
        side_lay.addLayout(brand_row)

        side_sep = QFrame()
        side_sep.setObjectName("sidebar_sep")
        side_sep.setFixedHeight(1)
        side_lay.addWidget(side_sep)
        side_lay.addSpacing(4)

        def nav_btn(key: str, index: int) -> QPushButton:
            btn = QPushButton()
            btn.setObjectName("nav_btn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda: self._switch_page(index))
            self._text_entries.append((btn, key))
            side_lay.addWidget(btn)
            return btn

        self.general_nav = nav_btn("settings.general_tab", 0)
        self.api_nav = nav_btn("settings.api_tab", 1)
        self.stt_nav = nav_btn("settings.stt_tab", 2)

        side_lay.addStretch(1)

        footer_sep = QFrame()
        footer_sep.setObjectName("sidebar_sep")
        footer_sep.setFixedHeight(1)
        side_lay.addWidget(footer_sep)
        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setObjectName("sidebar_subtitle")
        side_lay.addWidget(version_label, 0, Qt.AlignHCenter)
        return sidebar

    # ----------------------------------------------------------- page builders

    def _build_general_page(self) -> QWidget:
        page = QWidget()
        body_lay = self._scroll_layout(page)
        body_lay.setSpacing(12)

        # -- Appearance -----------------------------------------------------
        app_section, app_lay = self._section("settings.appearance", "palette")
        app_lay.addWidget(self._field_label("settings.theme"))
        self.theme_combo = QComboBox()
        for value, label in THEME_CHOICES:
            self.theme_combo.addItem(QIcon(_theme_swatch(value)), label, value)
        app_lay.addWidget(self.theme_combo)
        app_lay.addWidget(self._field_label("settings.language"))
        self.lang_combo = QComboBox()
        for value, label in LANGUAGES:
            self.lang_combo.addItem(label, value)
        app_lay.addWidget(self.lang_combo)
        app_lay.addWidget(self._field_label("settings.opacity"))
        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(8)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(60, 100)
        self.opacity_slider.setValue(92)
        self.opacity_value = QLabel("92%")
        self.opacity_value.setObjectName("muted")
        self.opacity_value.setMinimumWidth(44)
        self.opacity_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity_value)
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_value.setText(f"{v}%"))
        app_lay.addLayout(opacity_row)
        app_lay.addWidget(self._field_label("settings.window_width"))
        width_row = QHBoxLayout()
        width_row.setSpacing(8)
        self.win_width = QSpinBox()
        self.win_width.setRange(WINDOW_MIN_WIDTH, WINDOW_MAX_WIDTH)
        self.win_width.setValue(DEFAULT_WINDOW_WIDTH)
        self.win_width.setSuffix(t("settings.px_suffix"))
        width_row.addWidget(self.win_width)
        width_row.addStretch(1)
        app_lay.addLayout(width_row)
        app_lay.addWidget(self._field_label("settings.window_height"))
        height_row = QHBoxLayout()
        height_row.setSpacing(8)
        self.win_height = QSpinBox()
        self.win_height.setRange(WINDOW_MIN_HEIGHT, WINDOW_MAX_HEIGHT)
        self.win_height.setValue(DEFAULT_WINDOW_HEIGHT)
        self.win_height.setSuffix(t("settings.px_suffix"))
        height_row.addWidget(self.win_height)
        height_row.addStretch(1)
        app_lay.addLayout(height_row)
        self.anim_check = QCheckBox()
        self._text_entries.append((self.anim_check, "settings.animation"))
        app_lay.addWidget(self.anim_check)
        body_lay.addWidget(app_section)

        # -- AI Memory --------------------------------------------------------
        mem_section, mem_lay = self._section("settings.memory", "notebook")
        self.memory_enabled_check = QCheckBox()
        self._text_entries.append((self.memory_enabled_check, "settings.memory_enable"))
        mem_lay.addWidget(self.memory_enabled_check)
        self.memory_text = QPlainTextEdit()
        self.memory_text.setObjectName("memory_field")
        self.memory_text.setPlaceholderText(t("settings.memory_placeholder"))
        self.memory_text.setMinimumHeight(110)
        self.memory_text.setMaximumHeight(220)
        mem_lay.addWidget(self.memory_text)
        memory_hint = self._text_label("hint", "settings.memory_hint")
        memory_hint.setWordWrap(True)
        mem_lay.addWidget(memory_hint)
        body_lay.addWidget(mem_section)

        # -- Application ----------------------------------------------------
        gen_section, gen_lay = self._section("settings.application", "settings")
        self.start_check = QCheckBox()
        self._text_entries.append((self.start_check, "settings.start_with_windows"))
        gen_lay.addWidget(self.start_check)
        self.history_check = QCheckBox()
        self._text_entries.append((self.history_check, "settings.remember_history"))
        gen_lay.addWidget(self.history_check)
        self.tray_check = QCheckBox()
        self._text_entries.append((self.tray_check, "settings.close_to_tray"))
        gen_lay.addWidget(self.tray_check)
        self.new_tab_check = QCheckBox()
        self._text_entries.append((self.new_tab_check, "settings.new_tab_on_hotkey"))
        gen_lay.addWidget(self.new_tab_check)
        body_lay.addWidget(gen_section)

        # -- Hotkey ---------------------------------------------------------
        hot_section, hot_lay = self._section("settings.hotkey", "keyboard")
        hot_lay.addWidget(self._field_label("settings.global_shortcut"))
        hot_row = QHBoxLayout()
        hot_row.setSpacing(8)
        self.hotkey_label = QLabel()
        self.hotkey_label.setObjectName("muted")
        hot_row.addWidget(self.hotkey_label, 1)
        self.change_btn = QPushButton()
        self.change_btn.setObjectName("ghost")
        self.change_btn.clicked.connect(self._capture_hotkey)
        self._text_entries.append((self.change_btn, "settings.change"))
        hot_row.addWidget(self.change_btn)
        hot_lay.addLayout(hot_row)
        self.hotkey_hint = self._status_label()
        hot_lay.addWidget(self.hotkey_hint)

        hot_lay.addWidget(self._field_label("settings.stt_shortcut"))
        stt_hot_row = QHBoxLayout()
        stt_hot_row.setSpacing(8)
        self.stt_hotkey_label = QLabel()
        self.stt_hotkey_label.setObjectName("muted")
        stt_hot_row.addWidget(self.stt_hotkey_label, 1)
        self.stt_change_btn = QPushButton()
        self.stt_change_btn.setObjectName("ghost")
        self.stt_change_btn.clicked.connect(self._capture_stt_hotkey)
        self._text_entries.append((self.stt_change_btn, "settings.change"))
        stt_hot_row.addWidget(self.stt_change_btn)
        hot_lay.addLayout(stt_hot_row)
        self.stt_hotkey_hint = self._status_label()
        hot_lay.addWidget(self.stt_hotkey_hint)
        body_lay.addWidget(hot_section)

        # -- Web Search (enable) -------------------------------------------
        ws_section, ws_lay = self._section("settings.web_search", "world-search")
        self.ws_enable_check = QCheckBox()
        self._text_entries.append((self.ws_enable_check, "settings.enable_web_search"))
        ws_lay.addWidget(self.ws_enable_check)
        body_lay.addWidget(ws_section)

        body_lay.addStretch(1)
        return page

    def _build_api_page(self) -> QWidget:
        page = QWidget()
        body_lay = self._scroll_layout(page)
        body_lay.setSpacing(12)

        # -- DeepSeek --------------------------------------------------------
        ds_section, ds_lay = self._section("settings.deepseek", "brain")
        ds_lay.addWidget(self._field_label("settings.api_url"))
        self.ds_url = QLineEdit()
        ds_lay.addWidget(self.ds_url)
        ds_lay.addWidget(self._field_label("settings.api_key"))
        self.ds_key = QLineEdit()
        self.ds_key.setEchoMode(QLineEdit.Password)
        ds_lay.addWidget(self.ds_key)
        ds_lay.addWidget(self._field_label("settings.model"))
        self.ds_model = QLineEdit()
        ds_lay.addWidget(self.ds_model)
        self.ds_status = self._status_label()
        ds_lay.addWidget(self.ds_status)
        self.ds_test_btn = QPushButton()
        self.ds_test_btn.setObjectName("ghost")
        self.ds_test_btn.clicked.connect(self._test_deepseek)
        self._text_entries.append((self.ds_test_btn, "settings.test_connection"))
        ds_lay.addWidget(self.ds_test_btn)
        body_lay.addWidget(ds_section)

        # -- Cloudflare Vision ----------------------------------------------
        vis_section, vis_lay = self._section("settings.vision", "eye")
        self.vis_enable_check = QCheckBox()
        self._text_entries.append((self.vis_enable_check, "settings.enable_vision"))
        self.vis_enable_check.toggled.connect(self._on_vision_toggle)
        vis_lay.addWidget(self.vis_enable_check)
        # API fields collapse when the vision toggle is off; the images are
        # then sent straight to the main text model.
        self.vis_fields = QWidget()
        vis_fields_lay = QVBoxLayout(self.vis_fields)
        vis_fields_lay.setContentsMargins(0, 0, 0, 0)
        vis_fields_lay.setSpacing(10)
        vis_fields_lay.addWidget(self._field_label("settings.account_id"))
        self.vis_account = QLineEdit()
        vis_fields_lay.addWidget(self.vis_account)
        vis_fields_lay.addWidget(self._field_label("settings.api_token"))
        self.vis_token = QLineEdit()
        self.vis_token.setEchoMode(QLineEdit.Password)
        vis_fields_lay.addWidget(self.vis_token)
        vis_fields_lay.addWidget(self._field_label("settings.vision_model"))
        self.vis_model = QLineEdit()
        vis_fields_lay.addWidget(self.vis_model)
        self.vis_status = self._status_label()
        vis_fields_lay.addWidget(self.vis_status)
        self.vis_test_btn = QPushButton()
        self.vis_test_btn.setObjectName("ghost")
        self.vis_test_btn.clicked.connect(self._test_vision)
        self._text_entries.append((self.vis_test_btn, "settings.test_connection"))
        vis_fields_lay.addWidget(self.vis_test_btn)
        vis_lay.addWidget(self.vis_fields)
        body_lay.addWidget(vis_section)

        # -- Web Search (Tavily / providers) ---------------------------------
        ws_section, ws_lay = self._section("settings.web_search", "world-search")
        ws_lay.addWidget(self._field_label("settings.provider"))
        self.ws_provider = QComboBox()
        for value, label in WEBSEARCH_PROVIDERS:
            self.ws_provider.addItem(label, value)
        self.ws_provider.currentIndexChanged.connect(self._on_provider_changed)
        ws_lay.addWidget(self.ws_provider)
        ws_lay.addWidget(self._field_label("settings.search_url"))
        self.ws_url = QLineEdit()
        ws_lay.addWidget(self.ws_url)
        ws_lay.addWidget(self._field_label("settings.search_key"))
        self.ws_key = QLineEdit()
        self.ws_key.setEchoMode(QLineEdit.Password)
        ws_lay.addWidget(self.ws_key)
        results_row = QHBoxLayout()
        results_row.setSpacing(8)
        results_row.addWidget(self._field_label("settings.max_results"), 0)
        self.ws_max_results = QSpinBox()
        self.ws_max_results.setRange(1, 20)
        self.ws_max_results.setValue(DEFAULT_WEBSEARCH_MAX_RESULTS)
        results_row.addWidget(self.ws_max_results)
        results_row.addStretch(1)
        ws_lay.addLayout(results_row)
        timeout_row = QHBoxLayout()
        timeout_row.setSpacing(8)
        timeout_row.addWidget(self._field_label("settings.search_timeout"), 0)
        self.ws_timeout = QSpinBox()
        self.ws_timeout.setRange(5, 120)
        self.ws_timeout.setSuffix(t("settings.sec_suffix"))
        self.ws_timeout.setValue(DEFAULT_WEBSEARCH_TIMEOUT)
        timeout_row.addWidget(self.ws_timeout)
        timeout_row.addStretch(1)
        ws_lay.addLayout(timeout_row)
        self.ws_status = self._status_label()
        ws_lay.addWidget(self.ws_status)
        self.ws_test_btn = QPushButton()
        self.ws_test_btn.setObjectName("ghost")
        self.ws_test_btn.clicked.connect(self._test_websearch)
        self._text_entries.append((self.ws_test_btn, "settings.test_connection"))
        ws_lay.addWidget(self.ws_test_btn)
        body_lay.addWidget(ws_section)

        body_lay.addStretch(1)
        return page

    def _build_stt_page(self) -> QWidget:
        page = QWidget()
        body_lay = self._scroll_layout(page)
        body_lay.setSpacing(12)

        # -- Speech-to-Text --------------------------------------------------
        stt_section, stt_lay = self._section("settings.stt_section", "microphone")

        self.stt_enable_check = QCheckBox()
        self._text_entries.append((self.stt_enable_check, "settings.enable_stt"))
        stt_lay.addWidget(self.stt_enable_check)

        stt_lay.addWidget(self._field_label("settings.microphone"))
        mic_row = QHBoxLayout()
        mic_row.setSpacing(8)
        self.stt_mic_combo = QComboBox()
        mic_row.addWidget(self.stt_mic_combo, 1)
        self.stt_mic_refresh = QPushButton()
        self.stt_mic_refresh.setObjectName("ghost")
        self.stt_mic_refresh.setIcon(create_icon(
            "refresh", 16,
            theme_colors(self.config.get("appearance", "theme", "dark"))["muted"], 1.6))
        self.stt_mic_refresh.setIconSize(QSize(16, 16))
        self.stt_mic_refresh.setToolTip(t("settings.refresh"))
        self.stt_mic_refresh.clicked.connect(self._refresh_mic_list)
        mic_row.addWidget(self.stt_mic_refresh)
        stt_lay.addLayout(mic_row)

        timeout_row = QHBoxLayout()
        timeout_row.setSpacing(8)
        timeout_row.addWidget(self._field_label("settings.silence_timeout"), 0)
        self.stt_silence = QDoubleSpinBox()
        self.stt_silence.setRange(0.5, 5.0)
        self.stt_silence.setSingleStep(0.1)
        self.stt_silence.setDecimals(1)
        self.stt_silence.setSuffix(t("stt.sec_suffix"))
        self.stt_silence.setValue(DEFAULT_STT_SILENCE_TIMEOUT)
        timeout_row.addWidget(self.stt_silence)
        timeout_row.addStretch(1)
        stt_lay.addLayout(timeout_row)

        stt_lay.addWidget(self._field_label("settings.vosk_model"))
        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        self.stt_model = QLineEdit()
        model_row.addWidget(self.stt_model, 1)
        self.stt_model_btn = QPushButton()
        self.stt_model_btn.setObjectName("ghost")
        self.stt_model_btn.clicked.connect(self._browse_model)
        self._text_entries.append((self.stt_model_btn, "settings.browse"))
        model_row.addWidget(self.stt_model_btn)
        stt_lay.addLayout(model_row)

        self.stt_model_hint = self._text_label("hint", "stt.model_hint")
        self.stt_model_hint.setWordWrap(True)
        stt_lay.addWidget(self.stt_model_hint)

        self.stt_status = self._status_label()
        stt_lay.addWidget(self.stt_status)
        body_lay.addWidget(stt_section)

        body_lay.addStretch(1)
        return page

    def _scroll_layout(self, page: QWidget) -> QVBoxLayout:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(2, 2, 2, 2)
        scroll.setWidget(body)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return body_lay

    # ------------------------------------------------------------ build helpers

    def _section(self, key: str, icon: str = None):
        """A section card with an integrated icon + title header.

        Returns (frame, content_layout).
        """
        frame = QFrame()
        frame.setObjectName("section_card")
        v = QVBoxLayout(frame)
        v.setContentsMargins(16, 13, 16, 14)
        v.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(9)
        if icon:
            lbl = QLabel()
            lbl.setFixedSize(17, 17)
            self._section_icons.append((lbl, icon))
            header.addWidget(lbl, 0, Qt.AlignVCenter)
        title = QLabel()
        title.setObjectName("section_header")
        self._text_entries.append((title, key))
        header.addWidget(title)
        header.addStretch(1)
        v.addLayout(header)
        return frame, v

    def _field_label(self, key: str) -> QLabel:
        return self._text_label("field_label", key)

    def _text_label(self, object_name: str, key: str) -> QLabel:
        label = QLabel()
        label.setObjectName(object_name)
        self._text_entries.append((label, key))
        return label

    def _status_label(self) -> QLabel:
        label = QLabel("")
        label.setObjectName("muted")
        label.setWordWrap(True)
        return label

    def _retranslate(self):
        for widget, key in self._text_entries:
            widget.setText(t(key))
        self.close_btn.setToolTip(t("common.close"))
        self.ws_timeout.setSuffix(t("settings.sec_suffix"))
        self.win_width.setSuffix(t("settings.px_suffix"))
        self.win_height.setSuffix(t("settings.px_suffix"))
        self.stt_silence.setSuffix(t("stt.sec_suffix"))
        self.stt_mic_refresh.setToolTip(t("settings.refresh"))
        if self.stt_mic_combo.count():
            self.stt_mic_combo.setItemText(0, t("stt.default_mic"))

    def _refresh_nav_icons(self):
        colors = theme_colors(self.config.get("appearance", "theme", "dark"))
        accent, muted = colors["accent"], colors["muted"]
        self.header_logo.setPixmap(
            create_icon("sparkles", 19, accent, 1.8).pixmap(19, 19))
        self.brand_logo.setPixmap(
            create_icon("sparkles", 20, accent, 1.8).pixmap(20, 20))
        for lbl, name in self._section_icons:
            lbl.setPixmap(create_icon(name, 16, muted, 1.6).pixmap(16, 16))
        for btn, name in ((self.general_nav, "adjustments-horizontal"),
                          (self.api_nav, "api"),
                          (self.stt_nav, "microphone")):
            color = accent if btn.isChecked() else muted
            btn.setIcon(create_icon(name, 16, color, 1.6))

    def _switch_page(self, index: int):
        self.stack.setCurrentIndex(index)
        self.general_nav.setChecked(index == 0)
        self.api_nav.setChecked(index == 1)
        self.stt_nav.setChecked(index == 2)
        self._refresh_nav_icons()
        if self.config.get("appearance", "animations", True):
            animate_fade_slide_in(self.stack.currentWidget(), 210, dx=16)

    def _apply_theme(self):
        self.setStyleSheet(make_stylesheet(self.config.get("appearance", "theme", "dark")))
        self._refresh_nav_icons()
        if self.isVisible() and self.config.get("appearance", "animations", True):
            animate_fade_in(self.card, 200)

    # ------------------------------------------------------------- STT helpers

    def _refresh_mic_list(self, select: str = None):
        """Populate the microphone combo from real Windows input devices."""
        current = self.stt_mic_combo.currentData() if self.stt_mic_combo.count() else None
        select = select if select is not None else current
        self.stt_mic_combo.clear()
        self.stt_mic_combo.addItem(t("stt.default_mic"), "")
        for _index, name in list_microphones():
            self.stt_mic_combo.addItem(name, name)
        if select is not None:
            idx = self.stt_mic_combo.findData(select)
            if idx >= 0:
                self.stt_mic_combo.setCurrentIndex(idx)

    def _browse_model(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(
            self, t("stt.model_dialog_title"), self.stt_model.text().strip())
        if path:
            self.stt_model.setText(path)

    # ------------------------------------------------------------- load/save

    def load_from_config(self):
        cfg = self.config
        self.ds_url.setText(cfg.get("deepseek", "api_url", DEFAULT_APP_URL))
        self.ds_key.setText(cfg.get_deepseek_key())
        self.ds_model.setText(cfg.get("deepseek", "model", DEFAULT_MODEL))
        self.vis_enable_check.setChecked(bool(cfg.get("vision", "enabled", True)))
        self.vis_fields.setVisible(self.vis_enable_check.isChecked())
        self.vis_account.setText(cfg.get("vision", "account_id", ""))
        self.vis_token.setText(cfg.get_vision_token())
        self.vis_model.setText(cfg.get("vision", "model", DEFAULT_VISION_MODEL))

        self._new_hotkey = None
        self.hotkey_label.setText(humanize_combo(cfg.get_hotkey()))
        self.hotkey_hint.setText("")
        self._stt_new_hotkey = None
        self.stt_hotkey_label.setText(
            humanize_combo(cfg.get_stt_hotkey() or DEFAULT_STT_HOTKEY))
        self.stt_hotkey_hint.setText("")
        self.sidebar_subtitle.setText(humanize_combo(cfg.get_hotkey()))

        theme = cfg.get("appearance", "theme", "dark")
        index = self.theme_combo.findData(theme)
        self.theme_combo.setCurrentIndex(index if index >= 0 else 0)
        lang = cfg.get("appearance", "language", "") or detect_system_language()
        index = self.lang_combo.findData(lang)
        self.lang_combo.setCurrentIndex(index if index >= 0 else 0)
        opacity = int(round(float(cfg.get("appearance", "opacity", 0.92)) * 100))
        self.opacity_slider.setValue(max(60, min(100, opacity)))
        self.win_width.setValue(max(
            WINDOW_MIN_WIDTH,
            min(WINDOW_MAX_WIDTH,
                int(cfg.get_window("width", DEFAULT_WINDOW_WIDTH)
                    or DEFAULT_WINDOW_WIDTH))))
        self.win_height.setValue(max(
            WINDOW_MIN_HEIGHT,
            min(WINDOW_MAX_HEIGHT,
                int(cfg.get_window("height", DEFAULT_WINDOW_HEIGHT)
                    or DEFAULT_WINDOW_HEIGHT))))
        self.anim_check.setChecked(bool(cfg.get("appearance", "animations", True)))

        self.memory_enabled_check.setChecked(bool(cfg.get("memory", "enabled", False)))
        self.memory_text.setPlainText(cfg.get("memory", "context", "") or "")

        self.start_check.setChecked(cfg.get("general", "start_with_windows", False) or is_start_with_windows())
        self.history_check.setChecked(bool(cfg.get("general", "remember_history", False)))
        self.tray_check.setChecked(bool(cfg.get("general", "close_to_tray", True)))
        self.new_tab_check.setChecked(
            bool(cfg.get("general", "open_new_tab_on_hotkey", True)))

        self.ws_enable_check.setChecked(bool(cfg.get("web_search", "enabled", False)))
        provider = cfg.get("web_search", "provider", DEFAULT_WEBSEARCH_PROVIDER)
        index = self.ws_provider.findData(provider)
        self.ws_provider.setCurrentIndex(index if index >= 0 else 0)
        self.ws_url.setText(cfg.get("web_search", "api_url", DEFAULT_WEBSEARCH_URL))
        self.ws_key.setText(cfg.get_websearch_key())
        self.ws_max_results.setValue(int(cfg.get("web_search", "max_results", 5) or 5))
        self.ws_timeout.setValue(int(cfg.get("web_search", "timeout", 15) or 15))

        self.stt_enable_check.setChecked(bool(cfg.get_stt("enabled", False)))
        self._refresh_mic_list(select=cfg.get_stt("microphone", ""))
        self.stt_silence.setValue(float(
            cfg.get_stt("silence_timeout", DEFAULT_STT_SILENCE_TIMEOUT)
            or DEFAULT_STT_SILENCE_TIMEOUT))
        self.stt_model.setText(cfg.get_stt("model_path", ""))
        model = self.stt_model.text().strip()
        if model and not model_is_valid(model):
            self.stt_status.setText(t("stt.model_not_found"))
            self.stt_status.setObjectName("status_err")
            self.stt_status.style().unpolish(self.stt_status)
            self.stt_status.style().polish(self.stt_status)
        else:
            self.stt_status.setText("")

        self.ds_status.setText("")
        self.vis_status.setText("")
        self.ws_status.setText("")
        self._retranslate()

    def _save(self):
        cfg = self.config
        cfg.set("deepseek", "api_url", self.ds_url.text().strip())
        cfg.set_deepseek_key(self.ds_key.text().strip())
        cfg.set("deepseek", "model", self.ds_model.text().strip())

        cfg.set("vision", "enabled", self.vis_enable_check.isChecked())
        cfg.set("vision", "account_id", self.vis_account.text().strip())
        cfg.set_vision_token(self.vis_token.text().strip())
        cfg.set("vision", "model", self.vis_model.text().strip())

        if self._new_hotkey:
            ok, error = self.hotkey_validator(self._new_hotkey)
            if not ok:
                QMessageBox.warning(self, t("settings.hotkey_warning_title"), error)
                self.hotkey_label.setText(humanize_combo(cfg.get_hotkey()))
                self._new_hotkey = None
                return
            cfg.set_hotkey(humanize_combo(self._new_hotkey))
            self._new_hotkey = None

        if self._stt_new_hotkey:
            ok, error = self.stt_hotkey_validator(self._stt_new_hotkey)
            if not ok:
                QMessageBox.warning(self, t("settings.hotkey_warning_title"), error)
                self.stt_hotkey_label.setText(
                    humanize_combo(cfg.get_stt_hotkey() or DEFAULT_STT_HOTKEY))
                self._stt_new_hotkey = None
                return
            cfg.set_stt_hotkey(humanize_combo(self._stt_new_hotkey))
            self._stt_new_hotkey = None

        cfg.set("appearance", "theme", self.theme_combo.currentData())
        cfg.set("appearance", "language", self.lang_combo.currentData())
        set_language(self.lang_combo.currentData())
        cfg.set("appearance", "opacity", self.opacity_slider.value() / 100.0)
        cfg.set("appearance", "animations", self.anim_check.isChecked())
        cfg.set_window("width", self.win_width.value())
        cfg.set_window("height", self.win_height.value())
        cfg.set("memory", "enabled", self.memory_enabled_check.isChecked())
        cfg.set("memory", "context", self.memory_text.toPlainText().strip())
        cfg.set("general", "start_with_windows", self.start_check.isChecked())
        cfg.set("general", "remember_history", self.history_check.isChecked())
        cfg.set("general", "close_to_tray", self.tray_check.isChecked())
        cfg.set("general", "open_new_tab_on_hotkey", self.new_tab_check.isChecked())

        cfg.set("web_search", "enabled", self.ws_enable_check.isChecked())
        cfg.set("web_search", "provider", self.ws_provider.currentData())
        cfg.set("web_search", "api_url", self.ws_url.text().strip())
        cfg.set_websearch_key(self.ws_key.text().strip())
        cfg.set("web_search", "max_results", self.ws_max_results.value())
        cfg.set("web_search", "timeout", self.ws_timeout.value())

        cfg.set_stt("enabled", self.stt_enable_check.isChecked())
        cfg.set_stt("microphone", self.stt_mic_combo.currentData() or "")
        cfg.set_stt("silence_timeout", self.stt_silence.value())
        cfg.set_stt("model_path", self.stt_model.text().strip())

        model = self.stt_model.text().strip()
        if model and not model_is_valid(model):
            QMessageBox.warning(self, t("settings.stt_section"),
                                t("stt.model_not_found"))

        cfg.save()
        set_start_with_windows(self.start_check.isChecked())
        self.applied.emit()
        self.hide_animated()

    def _on_close_clicked(self):
        self.hide_animated()

    # ----------------------------------------------------------- hotkey capture

    def _capture_hotkey(self):
        dialog = _HotkeyCaptureDialog(self)
        dialog.comboCaptured.connect(self._on_hotkey_captured)
        dialog.exec()

    def _on_hotkey_captured(self, combo: str):
        ok, error = self.hotkey_validator(combo)
        if not ok:
            QMessageBox.warning(self, t("settings.hotkey_warning_title"), error)
            return
        self._new_hotkey = combo
        self.hotkey_label.setText(humanize_combo(combo))
        self.hotkey_hint.setText(t("settings.hotkey_change_hint"))

    def _capture_stt_hotkey(self):
        dialog = _HotkeyCaptureDialog(self)
        dialog.comboCaptured.connect(self._on_stt_hotkey_captured)
        dialog.exec()

    def _on_stt_hotkey_captured(self, combo: str):
        ok, error = self.stt_hotkey_validator(combo)
        if not ok:
            QMessageBox.warning(self, t("settings.hotkey_warning_title"), error)
            return
        self._stt_new_hotkey = combo
        self.stt_hotkey_label.setText(humanize_combo(combo))
        self.stt_hotkey_hint.setText(t("settings.hotkey_change_hint"))

    # ------------------------------------------------------------- test buttons

    def _set_status(self, label: QLabel, text: str, ok: bool = None):
        label.setText(text)
        if ok is True:
            label.setObjectName("status_ok")
        elif ok is False:
            label.setObjectName("status_err")
        else:
            label.setObjectName("muted")
        label.style().unpolish(label)
        label.style().polish(label)

    def _test_deepseek(self):
        self._set_status(self.ds_status, t("settings.testing"))
        self.ds_test_btn.setEnabled(False)
        url = self.ds_url.text().strip()
        key = self.ds_key.text().strip()
        model = self.ds_model.text().strip()

        def fn():
            client = DeepSeekClient(api_url=url, api_key=key, model=model)
            return client.test_connection()

        def on_done(result):
            self.ds_test_btn.setEnabled(True)
            self._set_status(self.ds_status, t("settings.success", result=result), True)

        def on_error(message, detail):
            self.ds_test_btn.setEnabled(True)
            self._set_status(self.ds_status, t("settings.err_prefix", message=message), False)
            self._show_detail(t("settings.detail_error_api"), message, detail)

        run_async(fn, on_done, on_error, parent=self)

    def _test_vision(self):
        self._set_status(self.vis_status, t("settings.testing"))
        self.vis_test_btn.setEnabled(False)
        account = self.vis_account.text().strip()
        token = self.vis_token.text().strip()
        model = self.vis_model.text().strip()

        def fn():
            client = CloudflareVisionClient(account_id=account, api_token=token, model=model)
            return client.test_connection()

        def on_done(result):
            self.vis_test_btn.setEnabled(True)
            self._set_status(self.vis_status, t("settings.success", result=result[:120]), True)

        def on_error(message, detail):
            self.vis_test_btn.setEnabled(True)
            self._set_status(self.vis_status, t("settings.err_prefix", message=message), False)
            self._show_detail(t("settings.detail_error_vision"), message, detail)

        run_async(fn, on_done, on_error, parent=self)

    def _on_provider_changed(self):
        """Auto-fill the API URL when switching provider and the field is default."""
        current = self.ws_url.text().strip()
        known = set(PROVIDER_URLS.values())
        if not current or current in known:
            self.ws_url.setText(PROVIDER_URLS.get(self.ws_provider.currentData(), ""))

    def _on_vision_toggle(self, checked: bool):
        """Collapse the Cloudflare API fields when vision is off."""
        self.vis_fields.setVisible(checked)


    def _test_websearch(self):
        self._set_status(self.ws_status, t("settings.testing"))
        self.ws_test_btn.setEnabled(False)
        provider = self.ws_provider.currentData()
        url = self.ws_url.text().strip()
        key = self.ws_key.text().strip()
        max_results = self.ws_max_results.value()
        timeout = self.ws_timeout.value()

        def fn():
            client = WebSearchClient(
                provider=provider, api_url=url, api_key=key,
                max_results=max_results, timeout=timeout)
            return client.test(timeout=timeout)

        def on_done(result):
            self.ws_test_btn.setEnabled(True)
            self._set_status(self.ws_status, t("settings.success", result=result), True)

        def on_error(message, detail):
            self.ws_test_btn.setEnabled(True)
            self._set_status(self.ws_status, t("settings.err_prefix", message=message), False)
            self._show_detail(t("settings.detail_error_websearch"), message, detail)

        run_async(fn, on_done, on_error, parent=self)

    def _show_detail(self, title, message, detail):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(message)
        if detail:
            box.setDetailedText(detail)
        box.setIcon(QMessageBox.Warning)
        box.exec()

    # -------------------------------------------------------------- show/hide

    def position_centered(self):
        from PySide6.QtGui import QCursor
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.resize(int(geo.width() * 0.52), int(geo.height() * 0.8))
        self.move(geo.x() + (geo.width() - self.width()) // 2,
                  geo.y() + (geo.height() - self.height()) // 2)

    def show_animated(self):
        if self.config.get("appearance", "animations", True):
            self.setWindowOpacity(0.0)
            self.show()
            self.raise_()
            self.activateWindow()
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(170)
            anim.setStartValue(0.0)
            anim.setEndValue(self.config.get("appearance", "opacity", 0.92))
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self._anim = anim
        else:
            self.setWindowOpacity(self.config.get("appearance", "opacity", 0.92))
            self.show()
            self.raise_()
            self.activateWindow()

    def hide_animated(self):
        if self.config.get("appearance", "animations", True) and self.isVisible():
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(120)
            anim.setStartValue(self.windowOpacity())
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.InCubic)
            anim.finished.connect(self.hide)
            anim.start()
            self._anim = anim
        else:
            self.hide()

    def closeEvent(self, event):
        super().closeEvent(event)


class _HotkeyCaptureDialog(QDialog):
    comboCaptured = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)

        self._combo = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._card = QFrame()
        self._card.setObjectName("card")
        outer.addWidget(self._card)
        lay = QVBoxLayout(self._card)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)
        title = QLabel(t("hotkey.capture_title"))
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        self.combo_label = QLabel(t("hotkey.press_keys"))
        self.combo_label.setObjectName("hotkey_capture_value")
        self.combo_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.combo_label)

        hint = QLabel(t("hotkey.example"))
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.setMinimumSize(380, 210)

    def showEvent(self, event):
        super().showEvent(event)
        animate_fade_slide_in(self._card, 190, dy=10)

    @staticmethod
    def _modifier_parts(mods) -> list:
        parts = []
        if mods & Qt.ControlModifier:
            parts.append("Ctrl")
        if mods & Qt.AltModifier:
            parts.append("Alt")
        if mods & Qt.ShiftModifier:
            parts.append("Shift")
        if mods & Qt.MetaModifier:
            parts.append("Win")
        return parts

    def keyPressEvent(self, event: QKeyEvent):
        from utils.hotkey import vk_for_name
        key = event.key()
        mods = event.modifiers()

        if key == Qt.Key_Escape:
            self.reject()
            return

        # Enter confirms the captured combination.
        if key in (Qt.Key_Return, Qt.Key_Enter):
            if self._combo:
                self.comboCaptured.emit(self._combo)
                self.accept()
            return

        # Modifier-only presses update the pending display but do not confirm.
        if key in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta):
            pending = self._modifier_parts(mods)
            if pending:
                self.combo_label.setText(" + ".join(pending + ["..."]))
            return

        if key == Qt.Key_unknown:
            return

        name = self._key_name(key)
        if not name:
            return
        vk = vk_for_name(name)
        if vk is None:
            return
        parts = self._modifier_parts(mods)
        is_function = name.upper().startswith("F") and name[1:].isdigit()
        if not parts and not is_function:
            return

        self._combo = " + ".join(parts + [name])
        self.combo_label.setText(self._combo)

    def _key_name(self, key) -> str:
        names = {
            Qt.Key_Space: "Space", Qt.Key_Enter: "Enter", Qt.Key_Return: "Enter",
            Qt.Key_Escape: "Esc", Qt.Key_Tab: "Tab", Qt.Key_Backspace: "Backspace",
            Qt.Key_Delete: "Delete", Qt.Key_Insert: "Insert", Qt.Key_Home: "Home",
            Qt.Key_End: "End", Qt.Key_PageUp: "PageUp", Qt.Key_PageDown: "PageDown",
            Qt.Key_Up: "Up", Qt.Key_Down: "Down", Qt.Key_Left: "Left", Qt.Key_Right: "Right",
            Qt.Key_CapsLock: "CapsLock", Qt.Key_Print: "PrintScreen",
            Qt.Key_ScrollLock: "ScrollLock", Qt.Key_Pause: "Pause", Qt.Key_NumLock: "NumLock",
        }
        if key in names:
            return names[key]
        if 0x30 <= key <= 0x39:
            return chr(key)
        if 0x41 <= key <= 0x5A:
            return chr(key)
        if Qt.Key_F1 <= key <= Qt.Key_F24:
            return f"F{key - Qt.Key_F1 + 1}"
        return ""

    def accept(self):
        super().accept()

    def reject(self):
        super().reject()
