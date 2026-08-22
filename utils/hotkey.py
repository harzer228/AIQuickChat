"""Global hotkey via WinAPI RegisterHotKey + Qt native event filter.

Works system-wide (browser, game, editor, explorer) without admin rights and
without any third-party dependency. Handles the WM_HOTKEY message inside the
Qt event loop.
"""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

user32 = ctypes.windll.user32
user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL

_VK = {
    "SPACE": 0x20, "ENTER": 0x0D, "RETURN": 0x0D, "ESC": 0x1B, "ESCAPE": 0x1B,
    "TAB": 0x09, "BACKSPACE": 0x08, "DELETE": 0x2E, "INS": 0x2D, "INSERT": 0x2D,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "CAPSLOCK": 0x14, "PRINTSCREEN": 0x2C, "SCROLLLOCK": 0x91, "PAUSE": 0x13,
    "NUMLOCK": 0x90,
    "NUMPAD0": 0x60, "NUMPAD1": 0x61, "NUMPAD2": 0x62, "NUMPAD3": 0x63,
    "NUMPAD4": 0x64, "NUMPAD5": 0x65, "NUMPAD6": 0x66, "NUMPAD7": 0x67,
    "NUMPAD8": 0x68, "NUMPAD9": 0x69,
    "ADD": 0x6B, "SUBTRACT": 0x6D, "MULTIPLY": 0x6A, "DIVIDE": 0x6F,
    "DECIMAL": 0x6E, "SEPARATOR": 0x6C,
}

_MODIFIER_NAMES = {"CTRL", "CONTROL", "ALT", "SHIFT", "WIN", "WINDOWS", "WINKEY", "META", "SUPER", "CMD"}


def vk_for_name(name: str):
    name = name.upper().strip()
    if name in _VK:
        return _VK[name]
    if len(name) == 1 and name.isalpha():
        return ord(name.upper())
    if len(name) == 1 and name.isdigit():
        return ord(name)
    if name.startswith("F") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return 0x70 + int(name[1:]) - 1
    return None


def parse_combo(combo: str):
    """Return (modifiers, vk) for a combo like 'Ctrl + Space'. None if invalid."""
    parts = [p.strip() for p in (combo or "").split("+")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    mods = 0
    key_name = None
    for part in parts:
        up = part.upper()
        if up in ("CTRL", "CONTROL", "CONTROLKEY"):
            mods |= MOD_CONTROL
        elif up in ("ALT",):
            mods |= MOD_ALT
        elif up in ("SHIFT",):
            mods |= MOD_SHIFT
        elif up in ("WIN", "WINDOWS", "WINKEY", "META", "SUPER", "CMD"):
            mods |= MOD_WIN
        else:
            if key_name is not None:
                return None
            key_name = part
    if key_name is None:
        return None
    vk = vk_for_name(key_name)
    if vk is None:
        return None
    # A single plain key without any modifier is dangerous (e.g. "A" or "Space").
    if mods == 0 and not (key_name.upper().startswith("F") and key_name[1:].isdigit()):
        return None
    return mods, vk


class HotkeyConflictError(Exception):
    def __init__(self, combo):
        super().__init__(f"Комбинация '{combo}' уже занята системой или не поддерживается.")
        self.combo = combo


class HotkeyManager(QAbstractNativeEventFilter):
    """Global hotkey via RegisterHotKey bound to a window handle.

    Uses single inheritance from QAbstractNativeEventFilter so that PySide6
    dispatches the Python nativeEventFilter override (multiple inheritance
    with QObject silently breaks the dispatch). Signals are replaced by a
    plain callback to keep things reliable.
    """

    def __init__(self, callback=None, hotkey_id=0x5A4C):
        super().__init__()
        self._id = hotkey_id  # unique per manager instance
        self._combo = None
        self._registered = False
        self._hwnd = None
        self._callback = callback

    @property
    def combo(self):
        return self._combo

    @property
    def registered(self) -> bool:
        return self._registered

    def set_callback(self, callback):
        self._callback = callback

    def register(self, combo: str, hwnd=None) -> bool:
        parsed = parse_combo(combo)
        if parsed is None:
            raise HotkeyConflictError(combo)
        mods, vk = parsed
        if self._registered:
            previous, prev_hwnd = self._combo, self._hwnd
        else:
            previous, prev_hwnd = None, None
        self.unregister()
        hwnd = hwnd or self._hwnd
        ok = user32.RegisterHotKey(hwnd, self._id, mods | MOD_NOREPEAT, vk)
        if not ok:
            self._registered = False
            self._combo = None
            if previous:
                # The new combo is taken — restore the previously working one
                # so the app is not left without a hotkey at all.
                rollback = parse_combo(previous)
                if rollback is not None and user32.RegisterHotKey(
                        prev_hwnd or hwnd, self._id,
                        rollback[0] | MOD_NOREPEAT, rollback[1]):
                    self._registered = True
                    self._combo = previous
                    self._hwnd = prev_hwnd or hwnd
            raise HotkeyConflictError(combo)
        self._combo = combo
        self._registered = True
        self._hwnd = hwnd
        return True

    def set_hwnd(self, hwnd):
        self._hwnd = hwnd
        if self._registered:
            combo = self._combo
            self.register(combo, hwnd=hwnd)

    def unregister(self):
        if self._registered:
            user32.UnregisterHotKey(self._hwnd or None, self._id)
        self._registered = False
        self._combo = None

    def nativeEventFilter(self, eventType, message):
        if self._registered and eventType in (b"windows_generic_MSG", "windows_generic_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._id:
                if self._callback is not None:
                    self._callback()
                return True, 0
        return False, 0


def humanize_combo(combo: str) -> str:
    parts = [p.strip() for p in (combo or "").split("+")]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    order = []
    for name in ("Ctrl", "Alt", "Shift", "Win"):
        for part in parts:
            if part.upper() in ("CTRL", "CONTROL", "CONTROLKEY") and name == "Ctrl":
                order.append("Ctrl")
                break
            if part.upper() == "ALT" and name == "Alt":
                order.append("Alt")
                break
            if part.upper() == "SHIFT" and name == "Shift":
                order.append("Shift")
                break
            if part.upper() in ("WIN", "WINDOWS", "WINKEY", "META", "SUPER", "CMD") and name == "Win":
                order.append("Win")
                break
    seen = set()
    key = ""
    for part in parts:
        up = part.upper()
        if up in _MODIFIER_NAMES:
            continue
        key = part
    if key:
        order.append(key)
    unique = []
    for item in order:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return " + ".join(unique)
