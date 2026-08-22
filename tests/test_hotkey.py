"""Offline tests for the global hotkey utilities (no OS registration)."""

from utils.hotkey import (
    MOD_CONTROL,
    MOD_SHIFT,
    HotkeyManager,
    humanize_combo,
    parse_combo,
    vk_for_name,
)


def test_parse_basic_combo():
    assert parse_combo("Ctrl+Shift+V") == (MOD_CONTROL | MOD_SHIFT, ord("V"))
    assert parse_combo("Ctrl + Space") == (MOD_CONTROL, vk_for_name("SPACE"))


def test_parse_rejects_invalid():
    assert parse_combo("") is None
    assert parse_combo("   ") is None
    assert parse_combo("Ctrl") is None          # modifier only
    assert parse_combo("A") is None             # plain key is dangerous
    assert parse_combo("Foo+Bar+Baz") is None   # two non-modifier keys


def test_parse_function_key_without_modifiers():
    mods, vk = parse_combo("F9")
    assert mods == 0
    assert vk == vk_for_name("F9")


def test_vk_for_name():
    assert vk_for_name("Space") == 0x20
    assert vk_for_name("F1") == 0x70
    assert vk_for_name("Numpad5") == 0x65
    assert vk_for_name("NoSuchKey") is None


def test_humanize_combo_orders_modifiers():
    assert humanize_combo("SHIFT+CONTROL+v") == "Ctrl + Shift + v"
    assert humanize_combo("Ctrl+Space") == "Ctrl + Space"
    assert humanize_combo("") == ""


def test_manager_unregistered_state():
    mgr = HotkeyManager(hotkey_id=0x7FFF)
    assert not mgr.registered
    assert mgr.combo is None
    # unregister on a fresh manager is a no-op, not an error
    mgr.unregister()
