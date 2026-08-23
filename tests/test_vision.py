"""Vision toggle: direct image routing to the text model + settings collapse."""

import json

from PySide6.QtGui import QImage

from config import history_path


def _tab(chat):
    chat.start_new_chat()
    return chat._current_tab()


def _attach_image(chat, text=""):
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(0xFFFF0000)
    chat._set_pending_image(image, "test.png")
    chat.input.setPlainText(text)


def test_image_sent_directly_to_text_ai_when_vision_off(chat_window, monkeypatch):
    chat_window.config.set("vision", "enabled", False)
    tab = _tab(chat_window)
    _attach_image(chat_window, "что на картинке?")

    sent = []
    monkeypatch.setattr(
        chat_window, "_start_text_task",
        lambda tab_arg, text, web_search=False: sent.append(text))
    monkeypatch.setattr(
        chat_window, "_start_vision_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Cloudflare path used")))
    chat_window.send_current()

    assert sent == ["что на картинке?"]
    assert tab._pending_vision_bubble is None
    entry = tab.conversation[-1]
    assert entry["_image"] is True
    parts = entry["content"]
    assert isinstance(parts, list)
    assert parts[0] == {"type": "text", "text": "что на картинке?"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert tab.links and tab.links[-1][1] is entry


def test_image_without_text_sends_only_image_part(chat_window, monkeypatch):
    chat_window.config.set("vision", "enabled", False)
    tab = _tab(chat_window)
    _attach_image(chat_window)

    monkeypatch.setattr(
        chat_window, "_start_text_task",
        lambda tab_arg, text, web_search=False: None)
    chat_window.send_current()

    parts = tab.conversation[-1]["content"]
    assert [p["type"] for p in parts] == ["image_url"]


def test_image_goes_to_cloudflare_when_vision_enabled(chat_window, monkeypatch):
    assert chat_window._vision_enabled()  # default keeps the Cloudflare path
    tab = _tab(chat_window)
    _attach_image(chat_window, "что на картинке?")

    started = []
    monkeypatch.setattr(
        chat_window, "_start_vision_task",
        lambda *args, **kwargs: started.append(args))
    monkeypatch.setattr(
        chat_window, "_start_text_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("text path used")))
    chat_window.send_current()

    assert len(started) == 1
    assert tab._pending_vision_bubble is not None
    assert tab.conversation == []


def test_history_save_strips_image_parts(chat_window):
    chat_window.config.set("general", "remember_history", True)
    tab = _tab(chat_window)
    tab.conversation.append({
        "role": "user",
        "content": [
            {"type": "text", "text": "что на картинке?"},
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64,QUJD"}},
        ],
        "_image": True,
    })
    tab.conversation.append({"role": "assistant", "content": "кот"})
    chat_window._save_history()

    raw = history_path().read_text(encoding="utf-8")
    assert "image_url" not in raw
    saved = json.loads(raw)["tabs"][-1]
    assert saved["conversation"][0]["content"] == "что на картинке?"
    assert saved["display"][0] == {
        "role": "user", "text": "что на картинке?", "has_image": True}


def test_vision_toggle_collapses_settings_fields(chat_window):
    from ui.settings_window import SettingsWindow
    win = SettingsWindow(chat_window.config)
    win.load_from_config()
    win.show()
    win._switch_page(1)  # API page hosts the vision section
    try:
        assert win.vis_fields.isVisible()
        win.vis_enable_check.setChecked(False)
        assert not win.vis_fields.isVisible()
        assert win.vis_enable_check.isVisible()  # the checkbox itself stays
        win.vis_enable_check.setChecked(True)
        assert win.vis_fields.isVisible()
    finally:
        win.close()


def test_vision_enabled_roundtrip_via_settings(chat_window, monkeypatch):
    import ui.settings_window as sw
    monkeypatch.setattr(sw, "set_start_with_windows", lambda enabled: None)

    win = sw.SettingsWindow(chat_window.config)
    win.vis_enable_check.setChecked(False)
    win._save()
    assert chat_window.config.get("vision", "enabled", True) is False

    reloaded = sw.SettingsWindow(chat_window.config)
    reloaded.load_from_config()
    assert not reloaded.vis_enable_check.isChecked()
    assert reloaded.vis_fields.isHidden()
