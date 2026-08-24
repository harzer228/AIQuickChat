import os
import sys
from pathlib import Path

APP_NAME = "AIQuickChat"
APP_VERSION = "1.0.0"

DEFAULT_APP_URL = "https://routerai.ru/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_VISION_MODEL = "@cf/meta/llama-3.2-11b-vision-instruct"

# Web Search defaults
DEFAULT_WEBSEARCH_PROVIDER = "tavily"
DEFAULT_WEBSEARCH_URL = "https://api.tavily.com/search"
DEFAULT_WEBSEARCH_MAX_RESULTS = 5
DEFAULT_WEBSEARCH_TIMEOUT = 15
# Multi-search: let the model run several distinct queries per question.
DEFAULT_WEBSEARCH_MULTI_SEARCH = True
DEFAULT_WEBSEARCH_MAX_QUERIES = 3

# Speech-to-Text (local Vosk) defaults
DEFAULT_STT_SILENCE_TIMEOUT = 1.5
DEFAULT_STT_SAMPLE_RATE = 16000
DEFAULT_STT_HOTKEY = "Ctrl+Shift+Space"

# Chat window size limits
DEFAULT_WINDOW_WIDTH = 470
DEFAULT_WINDOW_HEIGHT = 640
WINDOW_MIN_WIDTH = 420
WINDOW_MAX_WIDTH = 900
WINDOW_MIN_HEIGHT = 500
WINDOW_MAX_HEIGHT = 1400

# Credential Manager targets
CRED_TARGET_DEEPSEEK = f"{APP_NAME}/deepseek-key"
CRED_TARGET_VISION = f"{APP_NAME}/cloudflare-token"
CRED_TARGET_WEBSEARCH = f"{APP_NAME}/web-search-key"


def is_frozen():
    return getattr(sys, "frozen", False)


def app_data_dir() -> Path:
    if is_frozen():
        base = os.environ.get("APPDATA") or str(Path.home())
        path = Path(base) / APP_NAME
    else:
        base = os.environ.get("APPDATA")
        if base:
            path = Path(base) / APP_NAME
        else:
            path = Path.home() / ".aiquickchat"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return app_data_dir() / "config.json"


def history_path() -> Path:
    return app_data_dir() / "history.json"


def default_run_command() -> str:
    if is_frozen():
        return f'"{sys.executable}"'
    script = Path(sys.argv[0]).resolve()
    return f'"{sys.executable}" "{script}"'


DEFAULT_CONFIG = {
    "deepseek": {
        "api_url": DEFAULT_APP_URL,
        "model": DEFAULT_MODEL,
    },
    "vision": {
        "enabled": True,
        "account_id": "",
        "model": DEFAULT_VISION_MODEL,
    },
    "web_search": {
        "enabled": False,
        "provider": DEFAULT_WEBSEARCH_PROVIDER,
        "api_url": DEFAULT_WEBSEARCH_URL,
        "max_results": DEFAULT_WEBSEARCH_MAX_RESULTS,
        "timeout": DEFAULT_WEBSEARCH_TIMEOUT,
        "multi_search": DEFAULT_WEBSEARCH_MULTI_SEARCH,
        "max_queries": DEFAULT_WEBSEARCH_MAX_QUERIES,
    },
    "hotkey": "Ctrl+Space",
    "stt_hotkey": DEFAULT_STT_HOTKEY,
    "memory": {
        "enabled": False,
        "context": "",
    },
    "speech_to_text": {
        "enabled": False,
        "model_path": "",
        "microphone": "",
        "silence_timeout": DEFAULT_STT_SILENCE_TIMEOUT,
    },
    "appearance": {
        "theme": "dark",
        "opacity": 0.92,
        "animations": True,
        "language": "",
    },
    "general": {
        "start_with_windows": False,
        "remember_history": False,
        "close_to_tray": True,
        "open_new_tab_on_hotkey": True,
    },
    "window": {
        "width": DEFAULT_WINDOW_WIDTH,
        "height": DEFAULT_WINDOW_HEIGHT,
    },
}
