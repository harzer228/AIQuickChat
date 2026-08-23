"""Attached documents: chips, send flow, short display in history."""

import json

from config import history_path


def _attach(chat, tmp_path, name="notes.txt", content="содержимое файла"):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    chat._attach_document(str(p))
    return p


def test_attach_shows_chip_and_remove(chat_window, tmp_path):
    chat = chat_window
    _attach(chat, tmp_path)
    assert len(chat.pending_docs) == 1
    assert chat.pending_docs[0][0] == "notes.txt"
    assert chat.doc_chips_row.isVisible()
    assert chat.send_btn.isEnabled()  # docs alone enable sending

    chat._remove_doc(0)
    assert chat.pending_docs == []
    assert not chat.doc_chips_row.isVisible()
    assert not chat.send_btn.isEnabled()


def test_attach_error_shows_nothing(chat_window, tmp_path):
    chat = chat_window
    p = tmp_path / "empty.txt"
    p.write_text("", encoding="utf-8")
    chat._attach_document(str(p))
    assert chat.pending_docs == []
    assert not chat.doc_chips_row.isVisible()


def test_send_with_docs_full_content_short_display(chat_window, monkeypatch, tmp_path):
    chat = chat_window
    tab = chat._current_tab()
    sent = []
    monkeypatch.setattr(
        chat, "_start_text_task",
        lambda tab_arg, text, web_search=False: sent.append(text))

    _attach(chat, tmp_path)
    chat.input.setPlainText("вопрос по файлу")
    chat.send_current()

    entry = tab.conversation[-1]
    assert entry["role"] == "user"
    assert entry["_files"] == ["notes.txt"]
    assert "вопрос по файлу" in entry["content"]
    assert "содержимое файла" in entry["content"]       # full text to the model
    assert "содержимое файла" not in entry["_display"]  # short display variant
    assert "notes.txt" in entry["_display"]
    assert chat.pending_docs == []
    assert chat.input.toPlainText() == ""
    assert sent  # the task was started for this tab


def test_send_docs_only_without_text(chat_window, monkeypatch, tmp_path):
    chat = chat_window
    tab = chat._current_tab()
    monkeypatch.setattr(chat, "_start_text_task",
                        lambda tab_arg, text, web_search=False: None)
    _attach(chat, tmp_path)
    chat.send_current()
    entry = tab.conversation[-1]
    assert "содержимое файла" in entry["content"]
    assert "notes.txt" in entry["_display"]


def test_history_saves_short_display_for_docs(chat_window, monkeypatch, tmp_path):
    chat = chat_window
    chat.config.set("general", "remember_history", True)
    monkeypatch.setattr(chat, "_start_text_task",
                        lambda tab_arg, text, web_search=False: None)
    _attach(chat, tmp_path)
    chat.input.setPlainText("прочитай")
    chat.send_current()
    chat._save_history()

    data = json.loads(history_path().read_text(encoding="utf-8"))
    last = data["tabs"][-1]
    assert "содержимое файла" in last["conversation"][-1]["content"]
    display_text = last["display"][-1]["text"]
    assert "содержимое файла" not in display_text
    assert "notes.txt" in display_text


def test_docs_message_not_editable(chat_window, monkeypatch, tmp_path):
    chat = chat_window
    monkeypatch.setattr(chat, "_start_text_task",
                        lambda tab_arg, text, web_search=False: None)
    _attach(chat, tmp_path)
    chat.input.setPlainText("вопрос")
    chat.send_current()
    bubble = chat._current_tab().links[-1][0]
    assert not chat._edit_allowed(bubble)
