"""Theme coverage for Studio's current light/dark token system."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "web" / "src" / "styles"


def test_studio_light_and_dark_theme_tokens_are_used():
    css = (STYLE / "tokens.css").read_text(encoding="utf-8")
    assert ":root {" in css
    assert ':root[data-theme="dark"]' in css
    for token in ("--card-color:", "--text-color:", "--primary-color:", "--border-color:"):
        assert css.count(token) >= 2


def test_history_dialog_uses_theme_and_small_screen_constraints():
    css = (STYLE / "yukina-shell.css").read_text(encoding="utf-8")
    dialog = css.split(".history-dialog {", 1)[1].split("}", 1)[0]
    assert "background: var(--card-color)" in dialog
    assert "color: var(--text-color)" in dialog
    assert "100vw - 32px" in dialog
    assert "overflow: auto" in dialog
