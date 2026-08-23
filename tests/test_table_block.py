"""Scrollable table blocks: splitter, natural sizing, cap, theme refresh."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from ui.widgets import (
    Bubble,
    _TableBlock,
    markdown_to_html,
    set_markdown_colors,
    split_markdown_blocks,
)

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
