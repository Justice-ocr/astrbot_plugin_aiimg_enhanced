from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC_FILES = [
    ROOT / "README.md",
    ROOT / "metadata.yaml",
]
MOJIBAKE_FRAGMENTS = [
    "\ufffd",
    "缁",
    "鍟",
    "閰",
    "鏂",
    "鐗",
    "杈",
    "绔",
    "闅",
    "鏄",
    "浣",
    "Â",
    "Ã",
]


def test_project_docs_are_clean_utf8():
    for path in DOC_FILES:
        text = path.read_text(encoding="utf-8")
        for fragment in MOJIBAKE_FRAGMENTS:
            assert fragment not in text, f"{path} contains mojibake fragment {fragment!r}"
