"""GUI tests for the chat window (offscreen): menus, editing, memory."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def _add(chat, tab, role, text, **extra):
    bubble = (chat._add_user_bubble if role == "user"
              else chat._add_assistant_bubble)(text, tab=tab)
    entry = {"role": role, "content": text, **extra}
    tab.conversation.append(entry)
    chat._link_bubble(tab, bubble, entry)
    return bubble


def _tab(chat):
    chat.start_new_chat()
    return chat._current_tab()


def test_input_starts_single_line(chat_window):
    height = chat_window.input.height()
    assert 38 <= height <= 48, height  # one line, not the 3-4 line sizeHint


def test_context_menu_policies_route_to_bubble(chat_window):
    tab = _tab(chat_window)
    bubble = _add(chat_window, tab, "user", "hello")
    assert bubble.label.contextMenuPolicy() == Qt.NoContextMenu


def test_copy_puts_markdown_in_clipboard(chat_window):
    tab = _tab(chat_window)
    bubble = _add(chat_window, tab, "user", "plain **bold** `code`")
    chat_window._on_bubble_action(bubble, "copy")
    assert QApplication.clipboard().text() == "plain **bold** `code`"


def test_delete_user_message_keeps_ai_reply(chat_window):
    tab = _tab(chat_window)
    user = _add(chat_window, tab, "user", "q")
    ai = _add(chat_window, tab, "assistant", "a")
    chat_window._on_bubble_action(user, "delete")
    assert [e["role"] for e in tab.conversation] == ["assistant"]
    assert tab.links and tab.links[0][0] is ai


def test_delete_ai_message(chat_window):
    tab = _tab(chat_window)
    _add(chat_window, tab, "user", "q")
    ai = _add(chat_window, tab, "assistant", "a")
    chat_window._on_bubble_action(ai, "delete")
    assert [e["role"] for e in tab.conversation] == ["user"]


def test_edit_allowed_only_for_last_user_message(chat_window):
    tab = _tab(chat_window)
    u1 = _add(chat_window, tab, "user", "q1")
    assert chat_window._edit_allowed(u1)
    _add(chat_window, tab, "assistant", "a1")
    assert not chat_window._edit_allowed(u1)  # reply arrived
    u2 = _add(chat_window, tab, "user", "q2")
    assert chat_window._edit_allowed(u2)
    assert not chat_window._edit_allowed(_add(
        chat_window, tab, "user", "vision", _image=True))


def test_edit_not_allowed_while_busy(chat_window):
    from ui.chat_window import _TaskState
    tab = _tab(chat_window)
    bubble = _add(chat_window, tab, "user", "q")
    chat_window._tasks[999] = _TaskState(999, tab)
    try:
        assert not chat_window._edit_allowed(bubble)
    finally:
        chat_window._tasks.pop(999, None)


def test_edit_updates_text_and_resends_to_ai(chat_window, monkeypatch):
    tab = _tab(chat_window)
    last = _add(chat_window, tab, "user", "last q")

    sent = []
    monkeypatch.setattr(
        chat_window, "_start_text_task",
        lambda tab_arg, text, web_search=False: sent.append((id(tab_arg), text)))
    monkeypatch.setattr(chat_window, "_edit_message_dialog",
                        lambda text: "edited question")
    chat_window._on_bubble_action(last, "edit")
    assert last.text() == "edited question"
    assert tab.conversation[-1]["content"] == "edited question"
    assert sent == [(id(tab), "edited question")]


def test_edit_of_last_with_reply_removes_it_and_resends(chat_window, monkeypatch):
    tab = _tab(chat_window)
    _add(chat_window, tab, "user", "q")
    _add(chat_window, tab, "assistant", "old")
    new_last = _add(chat_window, tab, "user", "final")

    sent = []
    monkeypatch.setattr(
        chat_window, "_start_text_task",
        lambda tab_arg, text, web_search=False: sent.append(text))
    monkeypatch.setattr(chat_window, "_edit_message_dialog",
                        lambda text: "v2")
    chat_window._on_bubble_action(new_last, "edit")
    assert [e["content"] for e in tab.conversation] == ["q", "old", "v2"]
    assert sent == ["v2"]


def test_memory_injected_into_system_prompt(chat_window):
    base = chat_window._system_prompt()
    chat_window.config.set("memory", "enabled", True)
    chat_window.config.set("memory", "context", "I prefer brief answers.")
    injected = chat_window._system_prompt()
    assert base in injected
    assert "I prefer brief answers." in injected
    chat_window.config.set("memory", "enabled", False)
    assert chat_window._system_prompt() == base


def test_hotkey_new_tab_setting_respected(chat_window):
    # default on: toggle-open (hidden -> show) adds a tab
    chat_window.hide()
    chat_window.config.set("general", "open_new_tab_on_hotkey", True)
    before = chat_window.tabs_widget.count()
    chat_window.start_new_chat()  # what toggle_chat calls when the setting is on
    assert chat_window.tabs_widget.count() == before + 1


def test_rapid_toggle_does_not_shrink_window(chat_window, monkeypatch):
    """Interrupting open/hide animations must not compound into a shrink."""
    from PySide6.QtCore import QEventLoop, QTimer

    def pump(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    chat_window.show_animated()
    pump(400)
    width, height = chat_window.width(), chat_window.height()

    for _ in range(20):
        chat_window.show_animated()
        pump(40)   # mid-animation (open runs 170 ms)
        chat_window.hide_animated()
        pump(40)   # mid-animation (hide runs 130 ms)
    chat_window.show_animated()
    pump(400)

    assert abs(chat_window.width() - width) <= 1
    assert abs(chat_window.height() - height) <= 1
