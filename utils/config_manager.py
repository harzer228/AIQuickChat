"""Configuration storage.

Non-secret settings live in config.json under %APPDATA%\\AIQuickChat.
Secret values (API keys / tokens) are stored in the Windows Credential
Manager via the WinAPI. If the Credential Manager is unavailable, keys fall
back to a lightly obfuscated (base64) copy inside config.json.
"""

import base64
import copy
import ctypes
import json
import os
import winreg
from ctypes import wintypes
from pathlib import Path

from config import (
    APP_NAME,
    CRED_TARGET_DEEPSEEK,
    CRED_TARGET_VISION,
    CRED_TARGET_WEBSEARCH,
    DEFAULT_CONFIG,
    config_path,
)

advapi32 = ctypes.windll.advapi32


class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", ctypes.c_wchar_p),
        ("Comment", ctypes.c_wchar_p),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
advapi32.CredWriteW.restype = wintypes.BOOL
advapi32.CredReadW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
    ctypes.POINTER(ctypes.POINTER(CREDENTIAL)),
]
advapi32.CredReadW.restype = wintypes.BOOL
advapi32.CredFree.argtypes = [ctypes.c_void_p]
advapi32.CredFree.restype = None
advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
advapi32.CredDeleteW.restype = wintypes.BOOL

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


class WindowsCredentialManager:
    """Minimal wrapper around the Windows Credential Manager (WinAPI)."""

    USER = "AIQuickChat"

    @staticmethod
    def save(target: str, secret: str) -> None:
        raw = secret.encode("utf-8")
        buf = ctypes.create_string_buffer(raw, len(raw))
        cred = CREDENTIAL()
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.UserName = WindowsCredentialManager.USER
        cred.CredentialBlobSize = len(raw)
        cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        if not advapi32.CredWriteW(ctypes.byref(cred), 0):
            raise ctypes.WinError()

    @staticmethod
    def read(target: str):
        pcred = ctypes.POINTER(CREDENTIAL)()
        if not advapi32.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
            return None
        try:
            blob_size = pcred.contents.CredentialBlobSize
            blob = ctypes.string_at(pcred.contents.CredentialBlob, blob_size)
            return blob.decode("utf-8")
        finally:
            advapi32.CredFree(pcred)

    @staticmethod
    def delete(target: str) -> None:
        advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0)


class ConfigManager:
    SECRETS_KEY = "secrets"

    def __init__(self, path=None):
        self.path = str(path or config_path())
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self._fallback_secrets = {}
        self._cred_manager_ok = self._probe_cred_manager()
        self.load()

    # -- credential manager probe --------------------------------------------

    @staticmethod
    def _probe_cred_manager() -> bool:
        target = f"{APP_NAME}/probe"
        try:
            WindowsCredentialManager.save(target, "probe")
            WindowsCredentialManager.delete(target)
            return True
        except Exception:
            return False

    @property
    def cred_manager_ok(self) -> bool:
        return self._cred_manager_ok

    # -- load / save ---------------------------------------------------------

    def load(self):
        p = Path(self.path)
        if p.exists():
            try:
                loaded = json.loads(p.read_text(encoding="utf-8"))
                self._merge(self.data, loaded)
                self._fallback_secrets = loaded.get(self.SECRETS_KEY, {}) or {}
            except Exception:
                pass

    def _merge(self, dst: dict, src: dict):
        for key, value in (src or {}).items():
            if isinstance(value, dict) and isinstance(dst.get(key), dict):
                self._merge(dst[key], value)
            else:
                dst[key] = value

    def save(self):
        payload = copy.deepcopy(self.data)
        if self._cred_manager_ok:
            payload[self.SECRETS_KEY] = {}
        else:
            payload[self.SECRETS_KEY] = self._fallback_secrets
        tmp = self.path + ".tmp"
        Path(tmp).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    # -- plain settings ------------------------------------------------------

    def get(self, section: str, key: str, default=None):
        return self.data.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value):
        self.data.setdefault(section, {})[key] = value

    def get_window(self, key: str, default=None):
        return self.get("window", key, default)

    def set_window(self, key: str, value):
        self.set("window", key, value)

    def get_hotkey(self) -> str:
        return self.data.get("hotkey", "Ctrl+Space")

    def set_hotkey(self, value: str):
        self.data["hotkey"] = value

    def get_stt_hotkey(self) -> str:
        return self.data.get("stt_hotkey", "")

    def set_stt_hotkey(self, value: str):
        self.data["stt_hotkey"] = value

    # -- speech-to-text ------------------------------------------------------

    def get_stt(self, key: str, default=None):
        return self.get("speech_to_text", key, default)

    def set_stt(self, key: str, value):
        self.set("speech_to_text", key, value)

    # -- secrets -------------------------------------------------------------

    def get_secret(self, name: str) -> str:
        if self._cred_manager_ok:
            value = WindowsCredentialManager.read(name)
            if value is not None:
                return value
        encoded = self._fallback_secrets.get(name)
        if encoded:
            try:
                return base64.b64decode(encoded.encode("ascii")).decode("utf-8")
            except Exception:
                return ""
        return ""

    def set_secret(self, name: str, value: str):
        value = (value or "").strip()
        if self._cred_manager_ok:
            try:
                if value:
                    WindowsCredentialManager.save(name, value)
                else:
                    WindowsCredentialManager.delete(name)
                self._fallback_secrets.pop(name, None)
                return
            except OSError:
                pass
        if value:
            self._fallback_secrets[name] = base64.b64encode(value.encode("utf-8")).decode("ascii")
        else:
            self._fallback_secrets.pop(name, None)

    def get_deepseek_key(self) -> str:
        return self.get_secret(CRED_TARGET_DEEPSEEK)

    def set_deepseek_key(self, value: str):
        self.set_secret(CRED_TARGET_DEEPSEEK, value)

    def get_vision_token(self) -> str:
        return self.get_secret(CRED_TARGET_VISION)

    def set_vision_token(self, value: str):
        self.set_secret(CRED_TARGET_VISION, value)

    def get_websearch_key(self) -> str:
        return self.get_secret(CRED_TARGET_WEBSEARCH)

    def set_websearch_key(self, value: str):
        self.set_secret(CRED_TARGET_WEBSEARCH, value)


# ---------------------------------------------------------------------------
# Start with Windows (registry autostart, HKCU only - no admin needed).
# ---------------------------------------------------------------------------

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_start_with_windows(enabled: bool) -> bool:
    from config import default_run_command
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        try:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, default_run_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except OSError:
        return False


def is_start_with_windows() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE)
        try:
            winreg.QueryValueEx(key, APP_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False
