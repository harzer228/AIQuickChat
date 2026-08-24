"""Scrollable table blocks: splitter, adaptive sizing, cap, theme refresh."""

import math

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QLabel

from ui.widgets import (
    Bubble,
    _TableBlock,
    markdown_to_html,
    set_markdown_colors,
    split_markdown_blocks,
)


def _natural_width(md: str) -> int:
    """The width markdown_to_html(natural_tables=True) needs for ``md``."""
    doc = QTextDocument()
    doc.setHtml(markdown_to_html(md, natural_tables=True))
    return math.ceil(doc.idealWidth()) + 2

TABLE_MD = "| Имя | Возраст |\n|-----|---------|\n| Аня | 30 |\n| Боря | 40 |"


def setup_function(_func):
    set_markdown_colors({})


def kinds(blocks):
    return [kind for kind, _md in blocks]


def test_split_text_table_text():
    blocks = split_markdown_blocks("до\n" + TABLE_MD + "\nпосле")
    assert kinds(blocks) == ["text", "table", "text"]
    assert "до" in blocks[0][1]
    assert "Имя" in blocks[1][1]
    assert "после" in blocks[2][1]


def test_split_two_tables_and_plain_text():
    md = TABLE_MD + "\nмежду\n" + TABLE_MD
    blocks = split_markdown_blocks(md)
    assert kinds(blocks) == ["table", "text", "table"]


def test_split_without_tables_is_single_block():
    blocks = split_markdown_blocks("строка 1\n\nстрока 2")
    assert kinds(blocks) == ["text"]


def test_split_table_at_eof():
    blocks = split_markdown_blocks("вступление\n" + TABLE_MD)
    assert kinds(blocks) == ["text", "table"]
    assert blocks[1][1].count("\n") == 3


def test_natural_tables_drop_full_width():
    default = markdown_to_html(TABLE_MD)
    natural = markdown_to_html(TABLE_MD, natural_tables=True)
    assert 'width="100%"' in default
    assert 'width="100%"' not in natural
    assert "<th>Имя</th>" in natural


def test_bubble_renders_single_table_block(qapp):
    bubble = Bubble("assistant", 420)
    bubble.set_text("вот таблица:\n" + TABLE_MD)
    tables = bubble.findChildren(_TableBlock)
    assert len(tables) == 1
    assert "Аня" in tables[0]._html
    assert "<th>Имя</th>" in tables[0].label.text()  # actually displayed
    assert bubble.text() == "вот таблица:\n" + TABLE_MD  # copy source intact


def test_repeat_set_text_does_not_duplicate(qapp):
    bubble = Bubble("assistant", 420)
    md = "текст\n" + TABLE_MD
    for _ in range(3):
        bubble.set_text(md)  # streaming re-render
    assert len(bubble.findChildren(_TableBlock)) == 1
    # one leading text label + the label inside the scroll area
    plain_texts = [w for w in bubble.findChildren(QLabel) if w.parent() is bubble]
    assert len(plain_texts) == 1


def test_set_html_clears_blocks(qapp):
    bubble = Bubble("assistant", 380)
    bubble.set_text(TABLE_MD)
    assert bubble.findChildren(_TableBlock)
    bubble.set_html("<i>картинка</i>")
    assert not bubble.findChildren(_TableBlock)
    assert bubble.text() == ""


def test_tall_table_height_capped(qapp):
    rows = TABLE_MD.split("\n")[:2] + [f"| r{i} | {i} |" for i in range(60)]
    block = _TableBlock()
    block.set_markdown("\n".join(rows))
    assert block.maximumHeight() <= _TableBlock.MAX_HEIGHT
    assert block.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert block.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded


WIDE_TABLE_MD = (
    "| колонка-один | колонка-два | колонка-три | колонка-четыре |\n"
    "|---------------|--------------|-------------|----------------|\n"
    "| " + "оченьдлинноеслово " * 6 + "| значение | значение | значение |")


def test_fit_mode_stretches_full_width(qapp):
    block = _TableBlock()
    block.resize(_natural_width(TABLE_MD) + 120, 100)
    block.set_markdown(TABLE_MD)
    # The table fits the available width — adaptive flow render takes over.
    assert 'width="100%"' in block._html


def test_overflow_falls_back_to_natural_columns(qapp):
    block = _TableBlock()
    block.resize(max(140, _natural_width(WIDE_TABLE_MD) - 100), 100)
    block.set_markdown(WIDE_TABLE_MD)
    assert 'width="100%"' not in block._html


def test_render_puts_html_into_label_both_modes(qapp):
    # Fit mode (wide block, small table).
    fit = _TableBlock()
    fit.resize(_natural_width(TABLE_MD) + 120, 100)
    fit.set_markdown(TABLE_MD)
    assert "<th>" in fit.label.text()

    # Overflow mode (narrow block, wide table).
    overflow = _TableBlock()
    overflow.resize(max(140, _natural_width(WIDE_TABLE_MD) - 100), 100)
    overflow.set_markdown(WIDE_TABLE_MD)
    assert "<th>" in overflow.label.text()


def test_resize_switches_render_mode(qapp):
    natural_w = _natural_width(TABLE_MD)
    narrow = max(120, natural_w - 60)
    wide = natural_w + 150
    block = _TableBlock()
    block.show()  # hidden widgets do not get resizeEvent on resize()

    block.resize(narrow, 100)
    block.set_markdown(TABLE_MD)
    natural_first = 'width="100%"' not in block._html

    block.resize(wide, 100)  # resizeEvent re-renders for the new width
    fitted_after = 'width="100%"' in block._html

    block.resize(narrow, 100)
    natural_again = 'width="100%"' not in block._html
    assert natural_first and fitted_after and natural_again


def test_window_resize_updates_bubble_width(chat_window):
    chat = chat_window
    chat.config.set("appearance", "animations", False)
    tab = chat._current_tab()
    bubble = chat._add_assistant_bubble("с таблицей", tab=tab)
    entry = {"role": "assistant", "content": "с таблицей"}
    tab.conversation.append(entry)
    chat._link_bubble(tab, bubble, entry)  # _refresh_bubble_widths walks links
    assert bubble.maximumWidth() < 700  # created for the default window

    chat.resize(900, 700)
    loop = QEventLoop()
    QTimer.singleShot(60, loop.quit)
    loop.exec()

    # resizeEvent re-fits every linked bubble to the new _bubble_max_width().
    assert bubble.maximumWidth() == chat._bubble_max_width()
    assert bubble.maximumWidth() >= 700


def test_streaming_growth_keeps_one_block(qapp):
    bubble = Bubble("assistant", 420)
    stages = [
        "| a | b |",
        "| a | b |\n|---|---|",
        "| a | b |\n|---|---|\n| 1 | 2 |",
        "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |",
        "итог:\n" + "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |",
    ]
    for stage in stages:
        bubble.set_text(stage)
        assert len(bubble.findChildren(_TableBlock)) <= 1
    tables = bubble.findChildren(_TableBlock)
    assert len(tables) == 1
    assert "<td>3</td>" in tables[0]._html


def test_theme_change_recors_cached_table(qapp):
    set_markdown_colors({"border": "#010203", "surface_secondary": ""})
    bubble = Bubble("assistant", 420)
    bubble.set_text(TABLE_MD)
    table = bubble.findChildren(_TableBlock)[0]
    assert 'bordercolor="#010203"' in table._html

    # What ChatWindow._rerender_bubbles does on theme change: same md + force.
    set_markdown_colors({"border": "#040506", "surface_secondary": ""})
    bubble.set_text(bubble.text(), force=True)
    assert 'bordercolor="#040506"' in table._html
