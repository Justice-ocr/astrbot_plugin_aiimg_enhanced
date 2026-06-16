from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE_CSS = ROOT / "pages" / "Settings" / "style.css"


def test_light_paper_workbench_theme_tokens_are_used():
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert "--bg:#f7f6f2" in css
    assert "--surface:#ffffff" in css
    assert "--sidebar-bg:#f1eee7" in css
    assert "--accent:#3f6773" in css
    assert "--shadow:0 10px 24px rgba(31,35,40,.08)" in css
    assert "--shadow-soft:0 1px 3px rgba(31,35,40,.06)" in css


def test_light_paper_workbench_reduces_visual_weight():
    css = STYLE_CSS.read_text(encoding="utf-8")

    assert "linear-gradient(90deg,var(--accent),var(--code),transparent)" not in css
    assert ".card:hover{border-color:var(--border-strong);box-shadow:var(--shadow-soft)}" in css
    assert ".sidebar::before" in css
    assert "opacity:.28" in css
    assert "box-shadow:inset 3px 0 0 var(--accent)" in css
