"""Lightweight localization.

Strings live in ``locales/{en,ru}.json``. The current language is a module
level value set once at startup (from config / system) and updated when the
user changes it in Settings. ``t(key, **kwargs)`` resolves the string at call
time, so background worker threads pick up the current language automatically.
"""

import ctypes
import json
import os
import pathlib
import sys
from ctypes import wintypes

DEFAULT_LANG = "en"
SUPPORTED = {"en", "ru"}

# LANGID primary language ids (Windows).
_LANG_RUSSIAN = 0x19  # LANG_RUSSIAN

_current = None
_cache = {}


def locales_dir() -> pathlib.Path:
    """Return the directory containing the locale JSON files.

    In development it lives next to the source; when frozen (PyInstaller) the
    ``locales`` folder is expected to be bundled (--add-data) next to the app.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        base = pathlib.Path(meipass) if meipass else pathlib.Path(sys.executable).parent
        bundled = base / "locales"
        if (bundled / "en.json").exists():
            return bundled
    return pathlib.Path(__file__).resolve().parent.parent / "locales"


def _resolve(lang) -> str:
    if lang in SUPPORTED:
        return lang
    return DEFAULT_LANG


def _load(lang: str) -> dict:
    lang = _resolve(lang)
    if lang not in _cache:
        try:
            path = locales_dir() / f"{lang}.json"
            _cache[lang] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _cache[lang] = {}
    return _cache[lang]


def current_language() -> str:
    return _current or DEFAULT_LANG


def set_language(lang):
    global _current
    _current = _resolve(lang)


def t(key: str, **kwargs) -> str:
    """Return the translated string for ``key`` in the current language."""
    lang = _current or DEFAULT_LANG
    text = _load(lang).get(key)
    if text is None:
        text = _load(DEFAULT_LANG).get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError, IndexError):
            pass
    return text


def detect_system_language() -> str:
    """Detect the Windows UI language (ru/en), defaulting to English."""
    lang_env = os.environ.get("LANG", "").lower()
    if lang_env:
        base = lang_env.split("_")[0].split(".")[0]
        if base in SUPPORTED:
            return base
    try:
        user32 = ctypes.windll.user32
        user32.GetUserDefaultUILanguage.restype = wintypes.DWORD
        langid = user32.GetUserDefaultUILanguage() & 0x3FF
        if langid == _LANG_RUSSIAN:
            return "ru"
    except Exception:
        pass
    return DEFAULT_LANG
