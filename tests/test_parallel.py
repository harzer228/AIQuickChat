"""Parallel generation: several tabs can chat at the same time."""

import time

from PySide6.QtCore import QEventLoop, QTimer

from ui.chat_window import _TaskState


def _pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait_until(cond, timeout_ms=5000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        _pump(40)
        if cond():
            return True
    return False


class _StubDeepSeek:
    """Streams a canned reply derived from the last user message."""

    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def stream_message(self, messages, cancel_event=None):
        question = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg["content"]
                if isinstance(content, list):
                    content = " ".join(
                        p.get("text", "") for p in content if p.get("type") == "text")
                question = content
                break
        for word in (f"ответ[{question.strip() or 'пусто'}]", "готов"):
            if cancel_event is not None and cancel_event.is_set():
                return
            time.sleep(0.01)
            yield word + " "


def _tab(chat, index):
    widget = chat.tabs_widget.widget(index)
    chat.tabs_widget.setCurrentIndex(index)
    return widget


def test_send_blocked_in_busy_tab_allowed_in_idle_tab(chat_window, monkeypatch):
    chat = chat_window
    tab_a = _tab(chat, chat.tabs_widget.currentIndex())
    chat.start_new_chat()
    tab_b = chat._current_tab()

    chat._tasks[999] = _TaskState(999, tab_a)  # tab A is generating
    try:
        chat.tabs_widget.setCurrentWidget(tab_a)
        chat.input.setPlainText("вопрос А")
        chat.send_current()
        assert tab_a.conversation == []      # blocked: input still holds text
        assert chat.input.toPlainText() == "вопрос А"

        sent = []
        monkeypatch.setattr(
            chat, "_start_text_task",
            lambda tab_arg, text, web_search=False: sent.append((id(tab_arg), text)))
        chat.tabs_widget.setCurrentWidget(tab_b)
        chat.send_current()
        assert sent == [(id(tab_b), "вопрос А")]
        assert [e["content"] for e in tab_b.conversation] == ["вопрос А"]
        assert chat.input.toPlainText() == ""
    finally:
        chat._tasks.pop(999, None)


def test_two_tabs_generate_in_parallel(chat_window, monkeypatch):
    chat = chat_window
    chat.config.set("appearance", "animations", False)
    stub = _StubDeepSeek()
    monkeypatch.setattr(chat, "_make_deepseek", lambda task=None: stub)

    tab_a = _tab(chat, chat.tabs_widget.currentIndex())
    chat.input.setPlainText("первый")
    chat.send_current()

    chat.start_new_chat()
    tab_b = chat._current_tab()
    chat.input.setPlainText("второй")
    chat.send_current()

    def answered(tab, marker):
        return any(e.get("role") == "assistant" and marker in e["content"]
                   for e in tab.conversation)

    assert _wait_until(lambda: answered(tab_a, "первый")), tab_a.conversation
    assert _wait_until(lambda: answered(tab_b, "второй")), tab_b.conversation
    assert _wait_until(lambda: not chat._tasks), chat._tasks


def test_stop_stops_only_current_tab(chat_window, monkeypatch):
    chat = chat_window
    chat.config.set("appearance", "animations", False)

    class _SlowStub(_StubDeepSeek):
        def stream_message(self, messages, cancel_event=None):
            for word in ["медленно", "очень", "медленно", "пишем"]:
                if cancel_event is not None and cancel_event.is_set():
                    return
                time.sleep(0.15)
                yield word + " "

    monkeypatch.setattr(chat, "_make_deepseek", lambda task=None: _SlowStub())

    tab_a = _tab(chat, chat.tabs_widget.currentIndex())
    chat.input.setPlainText("А")
    chat.send_current()
    chat.start_new_chat()
    tab_b = chat._current_tab()
    chat.input.setPlainText("Б")
    chat.send_current()
    assert len(chat._tasks) == 2

    # Stop the task of the CURRENT tab (B); A keeps generating.
    chat.tabs_widget.setCurrentWidget(tab_b)
    chat._stop_generation()
    assert _wait_until(lambda: not any(t.tab is tab_b for t in chat._tasks.values()))
    assert any(t.tab is tab_a for t in chat._tasks.values())

    # A finishes normally afterwards.
    assert _wait_until(lambda: not chat._tasks), chat._tasks
    assert any(e.get("role") == "assistant" for e in tab_a.conversation)


def test_closing_busy_tab_blocked_idle_tab_closeable(chat_window):
    chat = chat_window
    tab_a = _tab(chat, chat.tabs_widget.currentIndex())
    chat.start_new_chat()
    tab_b = chat._current_tab()
    count = chat.tabs_widget.count()

    chat._tasks[999] = _TaskState(999, tab_a)
    try:
        chat.tabs_widget.setCurrentWidget(tab_a)
        chat._close_tab(chat.tabs_widget.indexOf(tab_a))
        assert chat.tabs_widget.count() == count      # busy tab kept

        chat.tabs_widget.setCurrentWidget(tab_b)
        chat._close_tab(chat.tabs_widget.indexOf(tab_b))
        assert chat.tabs_widget.count() == count - 1  # idle tab closed
    finally:
        chat._tasks.pop(999, None)


def test_composer_locks_only_for_busy_current_tab(chat_window):
    chat = chat_window
    chat.config.set("appearance", "animations", False)
    tab_a = _tab(chat, chat.tabs_widget.currentIndex())
    chat.start_new_chat()
    tab_b = chat._current_tab()

    chat._tasks[999] = _TaskState(999, tab_a)
    try:
        chat.tabs_widget.setCurrentWidget(tab_a)
        assert chat.input.isReadOnly()
        assert chat.attach_btn.isEnabled() is False
        chat.tabs_widget.setCurrentWidget(tab_b)
        assert not chat.input.isReadOnly()
        assert chat.attach_btn.isEnabled()
    finally:
        chat._tasks.pop(999, None)
        chat.tabs_widget.setCurrentWidget(tab_b)  # keep teardown off busy tab A
