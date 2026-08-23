"""markdown_to_html: tables, merged quotes, and the pre-existing features."""

from ui.widgets import markdown_to_html, set_markdown_colors


def setup_function(_func):
    set_markdown_colors({})


def test_table_basic():
    html = markdown_to_html("| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<table" in html and "</table>" in html
    assert "<th>a</th>" in html
    assert "<th>b</th>" in html
    assert "<td>1</td>" in html
    assert "<td>2</td>" in html


def test_table_alignment():
    html = markdown_to_html("| a | b | c |\n|:---|:---:|---:|\n| 1 | 2 | 3 |")
    assert 'align="center"' in html
    assert 'align="right"' in html


def test_table_inline_formatting_in_cells():
    html = markdown_to_html("| a |\n|---|\n| **bold** and `code` |")
    assert "<b>bold</b>" in html
    assert "<code>code</code>" in html


def test_table_surrounded_by_text():
    html = markdown_to_html("до\n| a | b |\n|---|---|\n| 1 | 2 |\nпосле")
    assert "<p>до</p>" in html
    assert "<td>1</td>" in html
    assert "<p>после</p>" in html


def test_pipe_line_without_separator_is_not_table():
    html = markdown_to_html("| просто строка | без сепаратора |")
    assert "<table" not in html
    assert "просто строка" in html


def test_consecutive_quotes_merge_into_one_block():
    html = markdown_to_html("> первая\n> вторая\n\nтекст")
    assert html.count("<blockquote>") == 1
    assert "первая" in html
    assert "вторая" in html
    assert "<br>" in html
    assert "<p>текст</p>" in html


def test_theme_colors_baked_into_table():
    set_markdown_colors({"border": "#123456", "surface_secondary": "#abcdef"})
    html = markdown_to_html("| a |\n|---|\n| 1 |")
    assert 'bordercolor="#123456"' in html
    assert 'bgcolor="#abcdef"' in html


def test_existing_features_still_work():
    html = markdown_to_html(
        "# Заголовок\n\n**жирный** *курсив* `код`\n\n- пункт\n\n"
        "> цитата\n\n---\n\n```python\nprint(1)\n```")
    assert "<h3>Заголовок</h3>" in html
    assert "<b>жирный</b>" in html
    assert "<i>курсив</i>" in html
    assert "<code>код</code>" in html
    assert "<li>пункт</li>" in html
    assert "<blockquote>цитата</blockquote>" in html
    assert "<hr>" in html
    assert '<pre class="code">print(1)</pre>' in html
