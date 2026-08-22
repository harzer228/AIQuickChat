"""Theme completeness and stylesheet rendering (pure logic, Qt-free)."""

from ui.widgets import THEMES, make_stylesheet, resolve_theme, theme_colors

EXPECTED_KEYS = {
    "background", "surface", "surface_secondary", "text", "text_secondary",
    "border", "accent", "accent_hover", "accent_pressed", "accent_soft",
    "hover", "hover_soft", "input", "user_message", "user_message_text",
    "ai_message", "ai_message_text", "error", "error_border", "success",
    "tab", "tab_active", "tab_active_text", "tab_hover", "close_button",
    "close_button_hover_bg", "muted", "disabled", "user_bubble_bg",
    "user_bubble_text", "ai_bubble_bg", "ai_bubble_text", "input_bg",
    "scroll", "error_bg", "code_bg", "placeholder", "section_bg", "field_bg",
    "btn_bg", "btn_hover", "tooltip_bg", "tooltip_text",
}


def test_theme_registry_complete():
    assert set(THEMES) == {
        "dark", "light", "nord", "dracula", "solarized", "rose-pine",
        "catppuccin", "tokyo-night", "everforest", "gruvbox",
    }
    for name, palette in THEMES.items():
        missing = EXPECTED_KEYS - set(palette)
        assert not missing, f"theme {name} misses keys: {missing}"
        for key, value in palette.items():
            assert isinstance(value, str) and value, f"{name}.{key} empty"


def test_stylesheet_renders_for_every_theme():
    for name in THEMES:
        qss = make_stylesheet(name)
        assert qss and "QFrame#card" in qss
        # the accent colour (always a hex value) must be embedded
        assert THEMES[name]["accent"].lstrip("#") in qss
        # no unformatted f-string placeholders left behind
        assert "{c[" not in qss


def test_resolve_theme_fallbacks():
    assert resolve_theme("nord") == "nord"
    assert resolve_theme("bogus") == "dark"
    assert resolve_theme("") == "dark"
    assert resolve_theme(None) == "dark"
    assert resolve_theme("SYSTEM") in THEMES or resolve_theme("SYSTEM") in ("dark", "light")


def test_theme_colors_returns_palette():
    assert theme_colors("gruvbox") is THEMES["gruvbox"]
