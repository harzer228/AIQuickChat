"""Shared UI widgets, theming and helpers."""

import html
import re
import traceback

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from api.errors import APIError
from ui.icons import IconButton, create_pixmap, inline_icon_img
from utils.i18n import t

DEFAULT_ICON_COLOR = "#8A8A96"


# ---------------------------------------------------------------------------
# Themes — one centralized system for Dark / Light / System.
# ---------------------------------------------------------------------------

THEMES = {
    "dark": {
        # semantic palette
        "background": "#1C1D24",
        "surface": "rgba(28, 29, 36, 0.94)",
        "surface_secondary": "rgba(255,255,255,0.04)",
        "text": "#ECECF2",
        "text_secondary": "#8A8A96",
        "border": "rgba(255,255,255,0.09)",
        "accent": "#4F7CFF",
        "accent_hover": "#628AFF",
        "accent_pressed": "#3E66E0",
        "accent_soft": "rgba(79,124,255,0.20)",
        "hover": "rgba(255,255,255,0.13)",
        "hover_soft": "rgba(255,255,255,0.08)",
        "input": "rgba(255,255,255,0.05)",
        "user_message": "rgba(79,124,255,0.92)",
        "user_message_text": "#FFFFFF",
        "ai_message": "rgba(255,255,255,0.06)",
        "ai_message_text": "#ECECF2",
        "error": "rgba(220,60,60,0.16)",
        "error_border": "rgba(255,80,80,0.45)",
        "success": "#2EBD85",
        "tab": "rgba(255,255,255,0.04)",
        "tab_active": "#4F7CFF",
        "tab_active_text": "#FFFFFF",
        "tab_hover": "rgba(255,255,255,0.13)",
        "close_button": "#FF5C5C",
        "close_button_hover_bg": "rgba(220,60,60,0.75)",
        # legacy aliases (kept for existing call sites)
        "muted": "#8A8A96",
        "disabled": "rgba(255,255,255,0.15)",
        "user_bubble_bg": "rgba(79,124,255,0.92)",
        "user_bubble_text": "#FFFFFF",
        "ai_bubble_bg": "rgba(255,255,255,0.06)",
        "ai_bubble_text": "#ECECF2",
        "input_bg": "rgba(255,255,255,0.05)",
        "scroll": "rgba(255,255,255,0.18)",
        "error_bg": "rgba(220,60,60,0.16)",
        "code_bg": "rgba(0,0,0,0.30)",
        "placeholder": "#6A6A76",
        "section_bg": "rgba(255,255,255,0.04)",
        "field_bg": "rgba(255,255,255,0.05)",
        "btn_bg": "rgba(255,255,255,0.07)",
        "btn_hover": "rgba(255,255,255,0.13)",
        "tooltip_bg": "#2A2B32",
        "tooltip_text": "#ECECF2",
    },
    "light": {
        # semantic palette
        "background": "#F5F5F7",
        "surface": "#FFFFFF",
        "surface_secondary": "#F2F3F5",
        "text": "#1C1D22",
        "text_secondary": "#6C6C78",
        "border": "rgba(0,0,0,0.10)",
        "accent": "#3E63DD",
        "accent_hover": "#3357C9",
        "accent_pressed": "#2C4BB4",
        "accent_soft": "rgba(62,99,221,0.14)",
        "hover": "#E9EAEE",
        "hover_soft": "rgba(0,0,0,0.05)",
        "input": "#FFFFFF",
        "user_message": "#3E63DD",
        "user_message_text": "#FFFFFF",
        "ai_message": "#F2F3F5",
        "ai_message_text": "#1C1D22",
        "error": "rgba(220,60,60,0.10)",
        "error_border": "rgba(220,60,60,0.50)",
        "success": "#1FA36B",
        "tab": "#F2F3F5",
        "tab_active": "#3E63DD",
        "tab_active_text": "#FFFFFF",
        "tab_hover": "#E9EAEE",
        "close_button": "#E5484D",
        "close_button_hover_bg": "rgba(229,72,77,0.85)",
        # legacy aliases (kept for existing call sites)
        "muted": "#6C6C78",
        "disabled": "rgba(0,0,0,0.15)",
        "user_bubble_bg": "rgba(62,99,221,0.94)",
        "user_bubble_text": "#FFFFFF",
        "ai_bubble_bg": "rgba(0,0,0,0.05)",
        "ai_bubble_text": "#1C1D22",
        "input_bg": "#FFFFFF",
        "scroll": "rgba(0,0,0,0.22)",
        "error_bg": "rgba(220,60,60,0.10)",
        "code_bg": "rgba(0,0,0,0.06)",
        "placeholder": "#A0A0AC",
        "section_bg": "#F7F7F9",
        "field_bg": "#FFFFFF",
        "btn_bg": "rgba(0,0,0,0.06)",
        "btn_hover": "rgba(0,0,0,0.10)",
        "tooltip_bg": "#FFFFFF",
        "tooltip_text": "#1C1D22",
    },
    "nord": {
        # semantic palette
        "background": "#2E3440",
        "surface": "rgba(46, 52, 64, 0.95)",
        "surface_secondary": "rgba(216, 222, 233, 0.05)",
        "text": "#ECEFF4",
        "text_secondary": "#9DA5B4",
        "border": "rgba(216, 222, 233, 0.12)",
        "accent": "#88C0D0",
        "accent_hover": "#9CD2E0",
        "accent_pressed": "#6FA8BB",
        "accent_soft": "rgba(136, 192, 208, 0.20)",
        "hover": "rgba(216, 222, 233, 0.14)",
        "hover_soft": "rgba(216, 222, 233, 0.08)",
        "input": "rgba(216, 222, 233, 0.06)",
        "user_message": "#5E81AC",
        "user_message_text": "#ECEFF4",
        "ai_message": "rgba(216, 222, 233, 0.07)",
        "ai_message_text": "#ECEFF4",
        "error": "rgba(191, 97, 106, 0.16)",
        "error_border": "rgba(191, 97, 106, 0.50)",
        "success": "#A3BE8C",
        "tab": "rgba(216, 222, 233, 0.05)",
        "tab_active": "#88C0D0",
        "tab_active_text": "#2E3440",
        "tab_hover": "rgba(216, 222, 233, 0.13)",
        "close_button": "#BF616A",
        "close_button_hover_bg": "rgba(191, 97, 106, 0.80)",
        # legacy aliases (kept for existing call sites)
        "muted": "#9DA5B4",
        "disabled": "rgba(216, 222, 233, 0.16)",
        "user_bubble_bg": "#5E81AC",
        "user_bubble_text": "#ECEFF4",
        "ai_bubble_bg": "rgba(216, 222, 233, 0.07)",
        "ai_bubble_text": "#ECEFF4",
        "input_bg": "rgba(216, 222, 233, 0.06)",
        "scroll": "rgba(216, 222, 233, 0.20)",
        "error_bg": "rgba(191, 97, 106, 0.16)",
        "code_bg": "rgba(0, 0, 0, 0.30)",
        "placeholder": "#7B88A1",
        "section_bg": "rgba(216, 222, 233, 0.05)",
        "field_bg": "rgba(216, 222, 233, 0.06)",
        "btn_bg": "rgba(216, 222, 233, 0.08)",
        "btn_hover": "rgba(216, 222, 233, 0.14)",
        "tooltip_bg": "#3B4252",
        "tooltip_text": "#ECEFF4",
    },
    "dracula": {
        # semantic palette
        "background": "#282A36",
        "surface": "rgba(40, 42, 54, 0.95)",
        "surface_secondary": "rgba(248, 248, 242, 0.05)",
        "text": "#F8F8F2",
        "text_secondary": "#9BA0B5",
        "border": "rgba(248, 248, 242, 0.12)",
        "accent": "#BD93F9",
        "accent_hover": "#CBA6FF",
        "accent_pressed": "#A87BE8",
        "accent_soft": "rgba(189, 147, 249, 0.20)",
        "hover": "rgba(248, 248, 242, 0.14)",
        "hover_soft": "rgba(248, 248, 242, 0.08)",
        "input": "rgba(248, 248, 242, 0.06)",
        "user_message": "#BD93F9",
        "user_message_text": "#282A36",
        "ai_message": "rgba(248, 248, 242, 0.07)",
        "ai_message_text": "#F8F8F2",
        "error": "rgba(255, 85, 85, 0.14)",
        "error_border": "rgba(255, 85, 85, 0.50)",
        "success": "#50FA7B",
        "tab": "rgba(248, 248, 242, 0.05)",
        "tab_active": "#BD93F9",
        "tab_active_text": "#282A36",
        "tab_hover": "rgba(248, 248, 242, 0.13)",
        "close_button": "#FF5555",
        "close_button_hover_bg": "rgba(255, 85, 85, 0.80)",
        # legacy aliases (kept for existing call sites)
        "muted": "#9BA0B5",
        "disabled": "rgba(248, 248, 242, 0.16)",
        "user_bubble_bg": "#BD93F9",
        "user_bubble_text": "#282A36",
        "ai_bubble_bg": "rgba(248, 248, 242, 0.07)",
        "ai_bubble_text": "#F8F8F2",
        "input_bg": "rgba(248, 248, 242, 0.06)",
        "scroll": "rgba(248, 248, 242, 0.20)",
        "error_bg": "rgba(255, 85, 85, 0.14)",
        "code_bg": "rgba(0, 0, 0, 0.35)",
        "placeholder": "#6272A4",
        "section_bg": "rgba(248, 248, 242, 0.05)",
        "field_bg": "rgba(248, 248, 242, 0.06)",
        "btn_bg": "rgba(248, 248, 242, 0.08)",
        "btn_hover": "rgba(248, 248, 242, 0.14)",
        "tooltip_bg": "#343746",
        "tooltip_text": "#F8F8F2",
    },
    "solarized": {
        # semantic palette (Solarized Light)
        "background": "#FDF6E3",
        "surface": "#FFFBF0",
        "surface_secondary": "#EEE8D5",
        "text": "#073642",
        "text_secondary": "#657B83",
        "border": "rgba(7, 54, 66, 0.14)",
        "accent": "#268BD2",
        "accent_hover": "#1E7BB8",
        "accent_pressed": "#196A9F",
        "accent_soft": "rgba(38, 139, 210, 0.14)",
        "hover": "#E4DDC8",
        "hover_soft": "rgba(7, 54, 66, 0.06)",
        "input": "#FEFCF5",
        "user_message": "#268BD2",
        "user_message_text": "#FFFFFF",
        "ai_message": "#EEE8D5",
        "ai_message_text": "#073642",
        "error": "rgba(220, 50, 47, 0.10)",
        "error_border": "rgba(220, 50, 47, 0.50)",
        "success": "#859900",
        "tab": "#EEE8D5",
        "tab_active": "#268BD2",
        "tab_active_text": "#FFFFFF",
        "tab_hover": "#E4DDC8",
        "close_button": "#DC322F",
        "close_button_hover_bg": "rgba(220, 50, 47, 0.85)",
        # legacy aliases (kept for existing call sites)
        "muted": "#657B83",
        "disabled": "rgba(7, 54, 66, 0.18)",
        "user_bubble_bg": "#268BD2",
        "user_bubble_text": "#FFFFFF",
        "ai_bubble_bg": "#EEE8D5",
        "ai_bubble_text": "#073642",
        "input_bg": "#FEFCF5",
        "scroll": "rgba(7, 54, 66, 0.22)",
        "error_bg": "rgba(220, 50, 47, 0.10)",
        "code_bg": "rgba(7, 54, 66, 0.07)",
        "placeholder": "#93A1A1",
        "section_bg": "#F5EFD8",
        "field_bg": "#FEFCF5",
        "btn_bg": "rgba(7, 54, 66, 0.07)",
        "btn_hover": "rgba(7, 54, 66, 0.12)",
        "tooltip_bg": "#FFFBF0",
        "tooltip_text": "#073642",
    },
    "rose-pine": {
        # semantic palette (Rosé Pine)
        "background": "#191724",
        "surface": "rgba(25, 23, 36, 0.95)",
        "surface_secondary": "rgba(224, 222, 244, 0.05)",
        "text": "#E0DEF4",
        "text_secondary": "#908CAA",
        "border": "rgba(224, 222, 244, 0.12)",
        "accent": "#EBBCBA",
        "accent_hover": "#F3CFCD",
        "accent_pressed": "#D6A5A3",
        "accent_soft": "rgba(235, 188, 186, 0.18)",
        "hover": "rgba(224, 222, 244, 0.14)",
        "hover_soft": "rgba(224, 222, 244, 0.08)",
        "input": "rgba(224, 222, 244, 0.06)",
        "user_message": "#EBBCBA",
        "user_message_text": "#191724",
        "ai_message": "rgba(224, 222, 244, 0.07)",
        "ai_message_text": "#E0DEF4",
        "error": "rgba(235, 111, 146, 0.14)",
        "error_border": "rgba(235, 111, 146, 0.50)",
        "success": "#9CCFD8",
        "tab": "rgba(224, 222, 244, 0.05)",
        "tab_active": "#EBBCBA",
        "tab_active_text": "#191724",
        "tab_hover": "rgba(224, 222, 244, 0.13)",
        "close_button": "#EB6F92",
        "close_button_hover_bg": "rgba(235, 111, 146, 0.80)",
        # legacy aliases (kept for existing call sites)
        "muted": "#908CAA",
        "disabled": "rgba(224, 222, 244, 0.16)",
        "user_bubble_bg": "#EBBCBA",
        "user_bubble_text": "#191724",
        "ai_bubble_bg": "rgba(224, 222, 244, 0.07)",
        "ai_bubble_text": "#E0DEF4",
        "input_bg": "rgba(224, 222, 244, 0.06)",
        "scroll": "rgba(224, 222, 244, 0.20)",
        "error_bg": "rgba(235, 111, 146, 0.14)",
        "code_bg": "rgba(0, 0, 0, 0.35)",
        "placeholder": "#6E6A86",
        "section_bg": "rgba(224, 222, 244, 0.05)",
        "field_bg": "rgba(224, 222, 244, 0.06)",
        "btn_bg": "rgba(224, 222, 244, 0.08)",
        "btn_hover": "rgba(224, 222, 244, 0.14)",
        "tooltip_bg": "#26233A",
        "tooltip_text": "#E0DEF4",
    },
    "catppuccin": {
        # semantic palette (Catppuccin Mocha)
        "background": "#1E1E2E",
        "surface": "rgba(30, 30, 46, 0.95)",
        "surface_secondary": "rgba(205, 214, 244, 0.05)",
        "text": "#CDD6F4",
        "text_secondary": "#9399B2",
        "border": "rgba(205, 214, 244, 0.12)",
        "accent": "#CBA6F7",
        "accent_hover": "#DAB9FF",
        "accent_pressed": "#B48EEA",
        "accent_soft": "rgba(203, 166, 247, 0.18)",
        "hover": "rgba(205, 214, 244, 0.14)",
        "hover_soft": "rgba(205, 214, 244, 0.08)",
        "input": "rgba(205, 214, 244, 0.06)",
        "user_message": "#CBA6F7",
        "user_message_text": "#1E1E2E",
        "ai_message": "rgba(205, 214, 244, 0.07)",
        "ai_message_text": "#CDD6F4",
        "error": "rgba(243, 139, 168, 0.14)",
        "error_border": "rgba(243, 139, 168, 0.50)",
        "success": "#A6E3A1",
        "tab": "rgba(205, 214, 244, 0.05)",
        "tab_active": "#CBA6F7",
        "tab_active_text": "#1E1E2E",
        "tab_hover": "rgba(205, 214, 244, 0.13)",
        "close_button": "#F38BA8",
        "close_button_hover_bg": "rgba(243, 139, 168, 0.80)",
        # legacy aliases (kept for existing call sites)
        "muted": "#9399B2",
        "disabled": "rgba(205, 214, 244, 0.16)",
        "user_bubble_bg": "#CBA6F7",
        "user_bubble_text": "#1E1E2E",
        "ai_bubble_bg": "rgba(205, 214, 244, 0.07)",
        "ai_bubble_text": "#CDD6F4",
        "input_bg": "rgba(205, 214, 244, 0.06)",
        "scroll": "rgba(205, 214, 244, 0.20)",
        "error_bg": "rgba(243, 139, 168, 0.14)",
        "code_bg": "rgba(17, 17, 27, 0.55)",
        "placeholder": "#585B70",
        "section_bg": "rgba(205, 214, 244, 0.05)",
        "field_bg": "rgba(205, 214, 244, 0.06)",
        "btn_bg": "rgba(205, 214, 244, 0.08)",
        "btn_hover": "rgba(205, 214, 244, 0.14)",
        "tooltip_bg": "#313244",
        "tooltip_text": "#CDD6F4",
    },
    "tokyo-night": {
        # semantic palette (Tokyo Night)
        "background": "#1A1B26",
        "surface": "rgba(26, 27, 38, 0.95)",
        "surface_secondary": "rgba(192, 202, 245, 0.05)",
        "text": "#C0CAF5",
        "text_secondary": "#7C87A8",
        "border": "rgba(192, 202, 245, 0.12)",
        "accent": "#7AA2F7",
        "accent_hover": "#8FB3FF",
        "accent_pressed": "#6488E4",
        "accent_soft": "rgba(122, 162, 247, 0.20)",
        "hover": "rgba(192, 202, 245, 0.14)",
        "hover_soft": "rgba(192, 202, 245, 0.08)",
        "input": "rgba(192, 202, 245, 0.06)",
        "user_message": "#7AA2F7",
        "user_message_text": "#1A1B26",
        "ai_message": "rgba(192, 202, 245, 0.07)",
        "ai_message_text": "#C0CAF5",
        "error": "rgba(247, 118, 142, 0.14)",
        "error_border": "rgba(247, 118, 142, 0.50)",
        "success": "#9ECE6A",
        "tab": "rgba(192, 202, 245, 0.05)",
        "tab_active": "#7AA2F7",
        "tab_active_text": "#1A1B26",
        "tab_hover": "rgba(192, 202, 245, 0.13)",
        "close_button": "#F7768E",
        "close_button_hover_bg": "rgba(247, 118, 142, 0.80)",
        # legacy aliases (kept for existing call sites)
        "muted": "#7C87A8",
        "disabled": "rgba(192, 202, 245, 0.16)",
        "user_bubble_bg": "#7AA2F7",
        "user_bubble_text": "#1A1B26",
        "ai_bubble_bg": "rgba(192, 202, 245, 0.07)",
        "ai_bubble_text": "#C0CAF5",
        "input_bg": "rgba(192, 202, 245, 0.06)",
        "scroll": "rgba(192, 202, 245, 0.20)",
        "error_bg": "rgba(247, 118, 142, 0.14)",
        "code_bg": "rgba(16, 17, 26, 0.55)",
        "placeholder": "#565F89",
        "section_bg": "rgba(192, 202, 245, 0.05)",
        "field_bg": "rgba(192, 202, 245, 0.06)",
        "btn_bg": "rgba(192, 202, 245, 0.08)",
        "btn_hover": "rgba(192, 202, 245, 0.14)",
        "tooltip_bg": "#24283B",
        "tooltip_text": "#C0CAF5",
    },
    "everforest": {
        # semantic palette (Everforest dark)
        "background": "#2E383C",
        "surface": "rgba(46, 56, 60, 0.95)",
        "surface_secondary": "rgba(211, 198, 170, 0.05)",
        "text": "#D3C6AA",
        "text_secondary": "#9DA9A0",
        "border": "rgba(211, 198, 170, 0.12)",
        "accent": "#A7C080",
        "accent_hover": "#BCD194",
        "accent_pressed": "#8FA96B",
        "accent_soft": "rgba(167, 192, 128, 0.18)",
        "hover": "rgba(211, 198, 170, 0.14)",
        "hover_soft": "rgba(211, 198, 170, 0.08)",
        "input": "rgba(211, 198, 170, 0.06)",
        "user_message": "#A7C080",
        "user_message_text": "#2E383C",
        "ai_message": "rgba(211, 198, 170, 0.07)",
        "ai_message_text": "#D3C6AA",
        "error": "rgba(230, 126, 128, 0.14)",
        "error_border": "rgba(230, 126, 128, 0.50)",
        "success": "#83C092",
        "tab": "rgba(211, 198, 170, 0.05)",
        "tab_active": "#A7C080",
        "tab_active_text": "#2E383C",
        "tab_hover": "rgba(211, 198, 170, 0.13)",
        "close_button": "#E67E80",
        "close_button_hover_bg": "rgba(230, 126, 128, 0.80)",
        # legacy aliases (kept for existing call sites)
        "muted": "#9DA9A0",
        "disabled": "rgba(211, 198, 170, 0.16)",
        "user_bubble_bg": "#A7C080",
        "user_bubble_text": "#2E383C",
        "ai_bubble_bg": "rgba(211, 198, 170, 0.07)",
        "ai_bubble_text": "#D3C6AA",
        "input_bg": "rgba(211, 198, 170, 0.06)",
        "scroll": "rgba(211, 198, 170, 0.20)",
        "error_bg": "rgba(230, 126, 128, 0.14)",
        "code_bg": "rgba(0, 0, 0, 0.30)",
        "placeholder": "#859289",
        "section_bg": "rgba(211, 198, 170, 0.05)",
        "field_bg": "rgba(211, 198, 170, 0.06)",
        "btn_bg": "rgba(211, 198, 170, 0.08)",
        "btn_hover": "rgba(211, 198, 170, 0.14)",
        "tooltip_bg": "#3A464C",
        "tooltip_text": "#D3C6AA",
    },
    "gruvbox": {
        # semantic palette (Gruvbox dark)
        "background": "#282828",
        "surface": "rgba(40, 40, 40, 0.95)",
        "surface_secondary": "rgba(235, 219, 178, 0.05)",
        "text": "#EBDBB2",
        "text_secondary": "#A89984",
        "border": "rgba(235, 219, 178, 0.12)",
        "accent": "#FE8019",
        "accent_hover": "#FF9840",
        "accent_pressed": "#D96D0E",
        "accent_soft": "rgba(254, 128, 25, 0.18)",
        "hover": "rgba(235, 219, 178, 0.14)",
        "hover_soft": "rgba(235, 219, 178, 0.08)",
        "input": "rgba(235, 219, 178, 0.06)",
        "user_message": "#FE8019",
        "user_message_text": "#282828",
        "ai_message": "rgba(235, 219, 178, 0.07)",
        "ai_message_text": "#EBDBB2",
        "error": "rgba(251, 73, 52, 0.14)",
        "error_border": "rgba(251, 73, 52, 0.50)",
        "success": "#B8BB26",
        "tab": "rgba(235, 219, 178, 0.05)",
        "tab_active": "#FE8019",
        "tab_active_text": "#282828",
        "tab_hover": "rgba(235, 219, 178, 0.13)",
        "close_button": "#FB4934",
        "close_button_hover_bg": "rgba(251, 73, 52, 0.80)",
        # legacy aliases (kept for existing call sites)
        "muted": "#A89984",
        "disabled": "rgba(235, 219, 178, 0.16)",
        "user_bubble_bg": "#FE8019",
        "user_bubble_text": "#282828",
        "ai_bubble_bg": "rgba(235, 219, 178, 0.07)",
        "ai_bubble_text": "#EBDBB2",
        "input_bg": "rgba(235, 219, 178, 0.06)",
        "scroll": "rgba(235, 219, 178, 0.20)",
        "error_bg": "rgba(251, 73, 52, 0.14)",
        "code_bg": "rgba(0, 0, 0, 0.35)",
        "placeholder": "#7C6F64",
        "section_bg": "rgba(235, 219, 178, 0.05)",
        "field_bg": "rgba(235, 219, 178, 0.06)",
        "btn_bg": "rgba(235, 219, 178, 0.08)",
        "btn_hover": "rgba(235, 219, 178, 0.14)",
        "tooltip_bg": "#3C3836",
        "tooltip_text": "#EBDBB2",
    },
}


def resolve_theme(name: str) -> str:
    name = (name or "dark").lower()
    if name == "system":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            try:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "light" if value == 1 else "dark"
            finally:
                winreg.CloseKey(key)
        except OSError:
            return "dark"
    return name if name in THEMES else "dark"


def theme_colors(name: str) -> dict:
    return THEMES[resolve_theme(name)]


def make_stylesheet(theme_name: str) -> str:
    c = theme_colors(theme_name)
    return f"""
* {{ font-family: 'Segoe UI Variable', 'Segoe UI', 'Inter', sans-serif; }}

QFrame#card {{
    background-color: {c['surface']};
    border-radius: 18px;
    border: 1px solid {c['border']};
}}
QFrame#header_sep {{ background-color: {c['border']}; border: none; max-height: 1px; }}

QFrame#composer {{
    background-color: {c['input']}; border: 1px solid {c['border']};
    border-radius: 17px;
}}
QFrame#composer[focused="true"] {{ border-color: {c['accent']}; }}

QFrame#sidebar {{
    background-color: {c['surface_secondary']}; border: 1px solid {c['border']};
    border-radius: 14px;
}}
QLabel#sidebar_title {{ color: {c['text']}; font-size: 13px; font-weight: 700; }}
QLabel#sidebar_subtitle {{ color: {c['text_secondary']}; font-size: 10px; font-weight: 600; }}
QFrame#sidebar_sep {{ background-color: {c['border']}; border: none; max-height: 1px; }}

QLabel#section_header {{ color: {c['text']}; font-size: 13px; font-weight: 700; }}

QPlainTextEdit#memory_field {{
    background-color: {c['field_bg']}; border: 1px solid {c['border']};
    border-radius: 12px; color: {c['text']}; font-size: 12px; padding: 10px 12px;
    selection-background-color: {c['accent']};
}}
QPlainTextEdit#memory_field:hover {{ border-color: {c['text_secondary']}; }}
QPlainTextEdit#memory_field:focus {{ border-color: {c['accent']}; }}

QLabel#hotkey_capture_value {{
    color: {c['accent']}; font-size: 22px; font-weight: 700;
    font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
    background-color: {c['code_bg']}; border-radius: 12px; padding: 14px;
}}
QLabel#title {{ color: {c['text']}; font-size: 17px; font-weight: 700; letter-spacing: 0.2px; }}
QLabel#section_title {{ color: {c['text']}; font-size: 12px; font-weight: 700; letter-spacing: 0.8px; }}
QLabel#hint {{ color: {c['text_secondary']}; font-size: 11px; }}
QLabel#field_label {{ color: {c['text_secondary']}; font-size: 12px; font-weight: 500; }}
QLabel#muted {{ color: {c['text_secondary']}; font-size: 12px; }}
QLabel#status_ok {{ color: {c['success']}; font-size: 12px; }}
QLabel#status_err {{ color: {c['close_button']}; font-size: 12px; }}

QPushButton#iconbtn, QToolButton#iconbtn {{
    background: transparent; border: none; color: {c['text_secondary']};
    font-size: 16px; border-radius: 9px; padding: 5px 9px;
}}
QPushButton#iconbtn:hover, QToolButton#iconbtn:hover {{
    background-color: {c['hover_soft']}; color: {c['text']};
}}
QPushButton#iconbtn:pressed, QToolButton#iconbtn:pressed {{
    background-color: {c['hover']};
}}
QPushButton#iconbtn:checked, QToolButton#iconbtn:checked {{
    background-color: {c['accent_soft']}; color: {c['accent']};
}}

QFrame#websearch_banner {{
    background-color: {c['accent_soft']}; border: 1px solid {c['border']};
    border-radius: 10px;
}}
QLabel#sources_title {{ color: {c['text_secondary']}; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }}
QFrame#sources_sep {{ background-color: {c['border']}; }}

QPushButton#send {{
    background-color: {c['accent']}; color: {c['user_message_text']}; border: none;
    border-radius: 13px; font-size: 16px; min-width: 40px; min-height: 40px;
    font-weight: 600;
}}
QPushButton#send:hover {{ background-color: {c['accent_hover']}; }}
QPushButton#send:pressed {{ background-color: {c['accent_pressed']}; }}
QPushButton#send:disabled {{ background-color: {c['disabled']}; color: rgba(255,255,255,0.7); }}
QPushButton#send[stop="true"] {{ border-radius: 10px; }}

QPushButton#mic {{
    background-color: {c['btn_bg']}; color: {c['text_secondary']}; border: 1px solid transparent;
    border-radius: 12px; min-width: 34px; min-height: 34px;
}}
QPushButton#mic:hover {{ background-color: {c['hover']}; color: {c['text']}; }}
QPushButton#mic:disabled {{ background-color: {c['disabled']}; color: rgba(255,255,255,0.7); }}
QPushButton#mic[recording="true"] {{
    background-color: {c['accent']}; color: {c['user_message_text']}; border-radius: 10px;
}}
QPushButton#mic[recording="true"]:hover {{ background-color: {c['accent_hover']}; }}

QPushButton#primary {{
    background-color: {c['accent']}; color: {c['user_message_text']}; border: none;
    border-radius: 11px; padding: 9px 20px; font-size: 13px; font-weight: 600;
}}
QPushButton#primary:hover {{ background-color: {c['accent_hover']}; }}
QPushButton#primary:pressed {{ background-color: {c['accent_pressed']}; }}
QPushButton#primary:disabled {{ background-color: {c['disabled']}; color: rgba(255,255,255,0.7); }}

QPushButton#ghost {{
    background-color: {c['btn_bg']}; color: {c['text']}; border: 1px solid {c['border']};
    border-radius: 11px; padding: 8px 16px; font-size: 13px; font-weight: 500;
}}
QPushButton#ghost:hover {{ background-color: {c['hover']}; border-color: {c['text_secondary']}; }}
QPushButton#ghost:pressed {{ background-color: {c['hover_soft']}; }}

QPushButton#nav_btn {{
    background: transparent; color: {c['text_secondary']}; border: none;
    border-radius: 10px; padding: 10px 14px; font-size: 13px; font-weight: 600;
    text-align: left;
}}
QPushButton#nav_btn:hover {{ background-color: {c['hover_soft']}; color: {c['text']}; }}
QPushButton#nav_btn:checked {{ background-color: {c['accent_soft']}; color: {c['accent']}; }}
QStackedWidget#settings_stack {{ background: transparent; }}

QFrame#bubble_user {{ background-color: {c['user_message']}; border-radius: 16px; border-bottom-left-radius: 6px; }}
QFrame#bubble_assistant {{
    background-color: {c['ai_message']}; border-radius: 16px; border-top-left-radius: 6px;
    border: 1px solid {c['border']};
}}
QFrame#bubble_error {{ background-color: {c['error']}; border-radius: 16px; border: 1px solid {c['error_border']}; }}
QLabel#bubble_user {{ color: {c['user_message_text']}; background: transparent; border: none; font-size: 13px; }}
QLabel#bubble_assistant {{ color: {c['ai_message_text']}; background: transparent; border: none; font-size: 13px; }}
QLabel#bubble_error {{ color: {c['text']}; background: transparent; border: none; font-size: 13px; }}

QLabel pre.code {{
    background-color: {c['code_bg']}; color: {c['text']};
    border-radius: 8px; padding: 10px; font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
}}
QLabel code {{
    background-color: {c['code_bg']}; padding: 1px 5px; border-radius: 5px;
    font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
}}
QLabel blockquote {{ color: {c['text_secondary']}; border-left: 3px solid {c['accent']}; padding-left: 10px; }}

#doc_chip {{
    background-color: {c['surface_secondary']};
    border: 1px solid {c['border']};
    border-radius: 11px;
}}
#doc_chip QLabel {{
    background: transparent; border: none;
    color: {c['text']}; font-size: 12px;
}}

QTextEdit#input {{
    background-color: transparent; border: none;
    color: {c['text']}; font-size: 13px; padding: 9px 6px;
    selection-background-color: {c['accent']};
}}
QTextEdit#input:focus {{ border: none; }}
QTextEdit#input::placeholder {{ color: {c['placeholder']}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['scroll']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['text_secondary']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 6px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['scroll']}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{
    background-color: {c['tab']}; color: {c['text_secondary']};
    border: 1px solid {c['border']}; border-radius: 10px;
    padding: 5px 26px 5px 13px; margin-right: 5px; margin-top: 2px; font-size: 12px; font-weight: 500;
}}
QTabBar::tab:hover {{ background-color: {c['tab_hover']}; color: {c['text']}; }}
QTabBar::tab:selected {{ background-color: {c['tab_active']}; color: {c['tab_active_text']}; border-color: {c['tab_active']}; }}
QPushButton#tab_close_btn, QToolButton#tab_close_btn {{
    background: transparent; border: none; color: {c['close_button']};
    border-radius: 8px; margin-right: 4px;
}}
QPushButton#tab_close_btn:hover, QToolButton#tab_close_btn:hover {{
    background-color: {c['close_button_hover_bg']}; color: {c['user_message_text']};
}}
QTabBar::tab:selected QPushButton#tab_close_btn, QTabBar::tab:selected QToolButton#tab_close_btn {{
    color: {c['user_message_text']};
}}

QFrame#preview {{
    background-color: {c['surface_secondary']}; border: 1px dashed {c['border']};
    border-radius: 13px;
}}
QPushButton#preview_remove, QToolButton#preview_remove {{
    background-color: {c['btn_bg']}; color: {c['text']}; border: none;
    border-radius: 9px; min-width: 24px; min-height: 24px; font-size: 12px;
}}
QPushButton#preview_remove:hover, QToolButton#preview_remove:hover {{
    background-color: {c['close_button_hover_bg']}; color: {c['user_message_text']};
}}

QFrame#section {{
    background-color: {c['surface_secondary']}; border: 1px solid {c['border']};
    border-radius: 14px;
}}
QFrame#section_card {{
    background-color: {c['surface']}; border: 1px solid {c['border']};
    border-radius: 14px;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {c['field_bg']}; border: 1px solid {c['border']};
    border-radius: 10px; color: {c['text']}; font-size: 13px; padding: 8px 11px;
    selection-background-color: {c['accent']};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {c['text_secondary']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {c['text_secondary']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid {c['text_secondary']}; margin-right: 8px; }}
QComboBox QAbstractItemView {{
    background-color: {c['surface']}; color: {c['text']};
    border: 1px solid {c['border']}; border-radius: 8px; padding: 4px;
    selection-background-color: {c['accent']}; selection-color: {c['user_message_text']};
    outline: none;
}}
QCheckBox {{ color: {c['text']}; font-size: 13px; spacing: 9px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border: 1px solid {c['border']};
    border-radius: 6px; background: {c['field_bg']};
}}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{ background-color: {c['accent']}; border-color: {c['accent']}; }}
QCheckBox::indicator:checked:disabled {{ background-color: {c['disabled']}; }}

QSlider {{ min-height: 22px; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['field_bg']}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {c['accent']}; border: 2px solid {c['surface']};
    width: 16px; height: 16px; margin: -6px 0; border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{ background: {c['accent_hover']}; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}

QToolTip {{
    background-color: {c['tooltip_bg']}; color: {c['tooltip_text']};
    border: 1px solid {c['border']}; border-radius: 7px; padding: 5px 9px; font-size: 12px;
}}
QMenu {{
    background-color: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']};
    border-radius: 12px; padding: 6px;
}}
QMenu::item {{ padding: 7px 24px; border-radius: 7px; font-size: 13px; }}
QMenu::item:selected {{ background-color: {c['accent_soft']}; color: {c['accent']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 10px; }}

QStatusBar {{ background: transparent; color: {c['text_secondary']}; }}

QMessageBox {{ background-color: {c['surface']}; }}
QMessageBox QLabel {{ color: {c['text']}; font-size: 13px; }}
"""


# ---------------------------------------------------------------------------
# Lightweight markdown -> rich text
# ---------------------------------------------------------------------------

_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")

# Theme colors baked into rich-text markup (tables). Set by ChatWindow on
# theme apply; Qt QSS cannot style rich-text inner elements like tables.
_MARKDOWN_COLORS = {}


def set_markdown_colors(colors: dict):
    _MARKDOWN_COLORS.clear()
    _MARKDOWN_COLORS.update(colors or {})


def _inline(text: str) -> str:
    text = html.escape(text)
    text = _INLINE_CODE_RE.sub(r"<code>\1</code>", text)
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)
    return text


def _split_table_row(line: str) -> list:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [cell.strip() for cell in s.split("|")]


_TABLE_ALIGN_RE = re.compile(r"^:?-{3,}:?$")


def _table_alignment(cell: str) -> str:
    left = cell.startswith(":")
    right = cell.endswith(":")
    if left and right:
        return "center"
    if right:
        return "right"
    return "left"


def _is_table_separator(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(_TABLE_ALIGN_RE.match(c) for c in cells if c != "")


def _table_cell(tag: str, cell: str, align: str, header: bool) -> str:
    attrs = ""
    if header and _MARKDOWN_COLORS.get("surface_secondary"):
        attrs += f' bgcolor="{_MARKDOWN_COLORS["surface_secondary"]}"'
    if align and align != "left":
        attrs += f' align="{align}"'
    return f"<{tag}{attrs}>{_inline(cell)}</{tag}>"


def _table_html(header, aligns, rows) -> str:
    attrs = ['width="100%"', 'border="1"', 'cellspacing="0"', 'cellpadding="6"']
    border = _MARKDOWN_COLORS.get("border")
    if border:
        attrs.append(f'bordercolor="{border}"')
    parts = ["<table " + " ".join(attrs) + ">"]
    parts.append("<tr>" + "".join(
        _table_cell("th", cell, align, header=True)
        for cell, align in zip(header, aligns)) + "</tr>")
    for row in rows:
        parts.append("<tr>" + "".join(
            _table_cell("td", cell, align, header=False)
            for cell, align in zip(row, aligns)) + "</tr>")
    parts.append("</table>")
    return "".join(parts)


def markdown_to_html(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    out = []
    para = []
    list_items = []
    quote_lines = []
    table = None  # (header, aligns, rows) while inside a GFM pipe table
    in_code = False
    code_lines = []

    def flush_para():
        if para:
            out.append("<p>" + " ".join(_inline(x) for x in para) + "</p>")
            para.clear()

    def flush_list():
        if list_items:
            out.append("<ul>" + "".join(f"<li>{_inline(x)}</li>" for x in list_items) + "</ul>")
            list_items.clear()

    def flush_quote():
        # Consecutive ">" lines merge into a single bordered quote.
        if quote_lines:
            body = "<br>".join(_inline(x) if x else "<br>" for x in quote_lines)
            out.append(f"<blockquote>{body}</blockquote>")
            quote_lines.clear()

    def flush_table():
        nonlocal table
        if table is not None:
            header, aligns, rows = table
            out.append(_table_html(header, aligns, rows))
            table = None

    def flush_all():
        flush_para()
        flush_list()
        flush_quote()
        flush_table()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_all()
            if in_code:
                out.append('<pre class="code">' + html.escape("\n".join(code_lines)) + "</pre>")
                code_lines = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue
        # GFM table: header row followed by a |---|---| separator row.
        if (table is None and stripped.startswith("|")
                and i + 1 < len(lines) and _is_table_separator(lines[i + 1])):
            flush_para()
            flush_list()
            flush_quote()
            header = _split_table_row(stripped)
            aligns = [_table_alignment(c) for c in _split_table_row(lines[i + 1])]
            table = (header, aligns, [])
            i += 2
            continue
        if table is not None:
            if stripped.startswith("|"):
                table[2].append(_split_table_row(stripped))
                i += 1
                continue
            flush_table()
        if stripped.startswith("#"):
            flush_para()
            flush_list()
            flush_quote()
            level = min(len(stripped) - len(stripped.lstrip("#")), 4)
            out.append(f"<h{level + 2}>{_inline(stripped.lstrip('#').strip())}</h{level + 2}>")
        elif stripped.startswith(("- ", "* ", "• ")):
            flush_para()
            flush_quote()
            list_items.append(stripped[2:].strip())
        elif stripped in ("---", "***", "___"):
            flush_para()
            flush_list()
            flush_quote()
            out.append("<hr>")
        elif stripped.startswith(">"):
            flush_para()
            flush_list()
            quote_lines.append(stripped.lstrip(">").strip())
        elif not stripped:
            flush_para()
            flush_list()
            flush_quote()
        else:
            flush_list()
            flush_quote()
            para.append(stripped)
        i += 1
    flush_all()
    if in_code:
        out.append('<pre class="code">' + html.escape("\n".join(code_lines)) + "</pre>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class Bubble(QFrame):
    """Rounded chat bubble. sender in ('user', 'assistant', 'error').

    Right-click opens a context menu: Copy (always), plus Edit/Delete when
    the corresponding flags are enabled and ``modify_check`` allows it
    (e.g. no generation is running).
    """

    actionRequested = Signal(str)  # "copy" | "edit" | "delete"

    def __init__(self, sender="user", max_width=380, parent=None,
                 modify_check=None):
        super().__init__(parent)
        self.sender = sender
        self.setObjectName(f"bubble_{sender}")
        self.setMaximumWidth(max_width)
        self.menu_delete = False
        self._modify_check = modify_check
        self._edit_check = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(6)
        self.image_label = None
        self.label = QLabel()
        self.label.setObjectName(f"bubble_{sender}")
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # Route right-clicks on the text to the bubble's own context menu.
        self.label.setContextMenuPolicy(Qt.NoContextMenu)
        lay.addWidget(self.label)
        self._text = ""

    def set_modify_check(self, check):
        """Callable returning True while editing/deleting is allowed."""
        self._modify_check = check

    def set_edit_check(self, check):
        """Callable returning True while the Edit menu item should show."""
        self._edit_check = check

    def _can_modify(self) -> bool:
        return self._modify_check is None or bool(self._modify_check())

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        copy_act = menu.addAction(t("chat.copy_message"))
        can_modify = self._can_modify()
        edit_act = (menu.addAction(t("chat.edit_message"))
                    if self._edit_check is not None and self._edit_check()
                    else None)
        delete_act = (menu.addAction(t("chat.delete_message"))
                      if self.menu_delete and can_modify else None)
        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return
        if chosen is copy_act:
            self.actionRequested.emit("copy")
        elif edit_act is not None and chosen is edit_act:
            self.actionRequested.emit("edit")
        elif delete_act is not None and chosen is delete_act:
            self.actionRequested.emit("delete")

    def set_text(self, text: str):
        self._text = text
        self.label.setText(markdown_to_html(text))

    def set_html(self, html_text: str):
        self._text = ""
        self.label.setText(html_text)

    def set_image(self, pixmap: QPixmap):
        if self.image_label is None:
            self.image_label = QLabel()
            self.image_label.setObjectName("bubble_preview_image")
            self.image_label.setAlignment(Qt.AlignLeft)
            self.image_label.setContextMenuPolicy(Qt.NoContextMenu)
            self.layout().insertWidget(0, self.image_label)
        self.image_label.setPixmap(pixmap)

    def text(self) -> str:
        return self._text

    def add_detail_row(self, title: str, detail: str):
        """Expandable technical detail (for errors)."""
        toggle = QPushButton(title)
        toggle.setObjectName("ghost")
        toggle.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        detail_label = QLabel(html.escape(detail))
        detail_label.setObjectName("muted")
        detail_label.setWordWrap(True)
        detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail_label.setVisible(False)
        self.layout().addWidget(toggle)
        self.layout().addWidget(detail_label)

        def on_toggle():
            detail_label.setVisible(not detail_label.isVisible())
            toggle.setText(t("chat.hide_details") if detail_label.isVisible() else title)

        toggle.clicked.connect(on_toggle)

    def add_sources(self, sources, accent=None, muted=None):
        """Append a clickable 'Sources' list to the bubble."""
        if not sources:
            return
        if accent is None or muted is None:
            colors = theme_colors("dark")
            accent = accent or colors["accent"]
            muted = muted or colors["muted"]
        lay = self.layout()

        header = QLabel()
        header.setObjectName("sources_title")
        header.setText(inline_icon_img("link", muted, 12, 1.8) + " " + t("chat.sources_header"))
        lay.addWidget(header)

        sep = QFrame()
        sep.setObjectName("sources_sep")
        sep.setFixedHeight(1)
        lay.addWidget(sep)

        for i, src in enumerate(sources[:8], 1):
            title = (src.title or src.url or t("chat.source_n", i=i)).strip()
            url = (src.url or "").strip()
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            icon_label = QLabel()
            icon_label.setPixmap(create_pixmap("external-link", 12, muted, 1.8))
            link = QLabel(
                f'<a href="{html.escape(url)}" style="color:{accent};text-decoration:none;">'
                f'{html.escape(title)}</a>')
            link.setOpenExternalLinks(True)
            link.setCursor(Qt.PointingHandCursor)
            link.setToolTip(url)
            link.setWordWrap(True)
            link.setContextMenuPolicy(Qt.NoContextMenu)
            row.addWidget(icon_label, 0, Qt.AlignTop)
            row.addWidget(link, 1)
            container = QWidget()
            container.setLayout(row)
            lay.addWidget(container)


class ThinkingIndicator(QFrame):
    """Animated 'Thinking...' row shown while the API is working."""

    def __init__(self, max_width=380, color=None, parent=None):
        super().__init__(parent)
        self.setObjectName("bubble_assistant")
        self.setMaximumWidth(max_width)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        self.dot = QLabel()
        self.dot.setPixmap(create_pixmap("sparkles", 14, color or DEFAULT_ICON_COLOR, 1.6))
        lay.addWidget(self.dot)
        self.label = QLabel()
        self.label.setObjectName("muted")
        lay.addWidget(self.label)
        lay.addStretch(1)
        self._base = t("chat.thinking")
        self._dots = 0
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._dots = (self._dots + 1) % 4
        self.label.setText(self._base + "." * self._dots)

    def set_status(self, text: str):
        self._base = text
        self._dots = 0
        self.label.setText(text)

    def start(self, text: str = None):
        if text:
            self.set_status(text)
        else:
            self.set_status(t("chat.thinking"))
        self._timer.start()

    def stop(self):
        self._timer.stop()


class ImagePreview(QFrame):
    """Preview of a pasted/attached image with a remove button."""

    removeRequested = Signal()

    def __init__(self, max_height=120, parent=None):
        super().__init__(parent)
        self.setObjectName("preview")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        self.image_label = QLabel()
        self.image_label.setObjectName("muted")
        self.image_label.setScaledContents(False)
        lay.addWidget(self.image_label, 1)
        self.name_label = QLabel()
        self.name_label.setObjectName("muted")
        self.name_label.setWordWrap(True)
        lay.addWidget(self.name_label)
        remove = IconButton("x", tooltip=t("chat.remove_image_tooltip"), size=10,
                            color=DEFAULT_ICON_COLOR)
        remove.setObjectName("preview_remove")
        remove.setFixedSize(24, 24)
        remove.clicked.connect(self.removeRequested)
        lay.addWidget(remove)
        self._max_height = max_height

    def set_image(self, pixmap: QPixmap, name: str = ""):
        scaled = pixmap.scaledToHeight(
            self._max_height, Qt.SmoothTransformation)
        if scaled.width() > 200:
            scaled = scaled.scaled(
                200, self._max_height,
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.name_label.setText(name or t("chat.image_name"))


class DragHandle(QFrame):
    """A strip you can drag to move the frameless window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("drag_handle")
        self._dragging = False
        self._offset = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._offset = (event.globalPosition().toPoint()
                            - self.window().frameGeometry().topLeft())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.window().move(event.globalPosition().toPoint() - self._offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------

class TaskWorker(QObject):
    done = Signal(object)
    error = Signal(str, str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
            self.done.emit(result)
        except APIError as e:
            self.error.emit(e.message, e.detail)
        except Exception as e:
            self.error.emit(t("chat.unexpected_error", e=e), traceback.format_exc())


def run_async(fn, on_done, on_error, parent=None):
    """Run fn in a background thread; callbacks are invoked on the main thread.

    Strong references to the thread and worker are held until the thread
    finishes, otherwise CPython refcounting frees the worker immediately and
    the job never runs.
    """
    thread = QThread(parent)
    worker = TaskWorker(fn)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.done.connect(on_done)
    worker.error.connect(on_error)
    worker.done.connect(thread.quit)
    worker.error.connect(thread.quit)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(worker.deleteLater)

    holder = {"thread": thread, "worker": worker}

    def _release():
        holder.clear()

    thread.finished.connect(_release)
    thread.start()
    return thread


def _stop_widget_animations(widget):
    """Stop fade/slide animations still running on ``widget``.

    Restarting an animation replaces the graphics effect, deleting the old
    effect while its animation may still tick — which crashes with "Internal
    C++ object already deleted". Interrupted slide animations also leave the
    widget offset, so its position is restored to the animation's end value.
    """
    for attr in ("_aq_anim_op", "_aq_anim_pos"):
        anim = getattr(widget, attr, None)
        if anim is None:
            continue
        try:
            if attr == "_aq_anim_pos" and anim.state() == QPropertyAnimation.Running:
                end = anim.endValue()
                if end is not None:
                    widget.move(end)
            anim.stop()
        except RuntimeError:
            pass
        setattr(widget, attr, None)


def animate_fade_in(widget, duration: int = 160):
    """Fade a widget in from transparent. Lightweight, event-driven only."""
    _stop_widget_animations(widget)
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start()
    widget._aq_anim_op = anim
    return anim


def animate_fade_slide_in(widget, duration: int = 220, dx: int = 0, dy: int = 14):
    """Fade a widget in while it slides into place from a small offset."""
    _stop_widget_animations(widget)
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    target = widget.pos()
    start = target - QPoint(dx, dy)
    widget.move(start)

    anim_pos = QPropertyAnimation(widget, b"pos", widget)
    anim_pos.setDuration(duration)
    anim_pos.setStartValue(start)
    anim_pos.setEndValue(target)
    anim_pos.setEasingCurve(QEasingCurve.OutCubic)
    anim_pos.start()
    widget._aq_anim_pos = anim_pos

    anim_op = QPropertyAnimation(effect, b"opacity", widget)
    anim_op.setDuration(duration)
    anim_op.setStartValue(0.0)
    anim_op.setEndValue(1.0)
    anim_op.setEasingCurve(QEasingCurve.OutCubic)
    anim_op.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim_op.start()
    widget._aq_anim_op = anim_op
    return anim_op


def animate_fade_out(widget, duration: int = 130, on_hidden=None):
    """Fade a widget out; ``on_hidden`` runs after (typically widget.hide())."""
    _stop_widget_animations(widget)
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(QEasingCurve.InCubic)

    def _finished():
        widget.setGraphicsEffect(None)
        if on_hidden is not None:
            on_hidden()

    anim.finished.connect(_finished)
    anim.start()
    widget._aq_anim_op = anim
    return anim


def smooth_scroll(bar, target: int, duration: int = 260):
    """Animate a scrollbar from its current value to ``target``."""
    prev = getattr(bar, "_aq_scroll_anim", None)
    if prev is not None:
        try:
            prev.stop()
        except RuntimeError:
            pass
    anim = QPropertyAnimation(bar, b"value", bar)
    anim.setDuration(duration)
    anim.setStartValue(bar.value())
    anim.setEndValue(max(0, min(int(target), bar.maximum())))
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.start()
    bar._aq_scroll_anim = anim
    return anim
