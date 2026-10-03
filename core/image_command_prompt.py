from __future__ import annotations

import re


_SECTIONS = re.compile(
    r"(?<!\S)(?:(?P<flag>--negative)(?=\s|$)|"
    r"(?P<label>画师串|画师|正面|提示词|负面提示词|负面)\s*[:：])"
)


def split_negative_prompt(text: str) -> tuple[str, str | None]:
    """Parse optional labeled sections without tokenizing tag weights."""
    sections = list(_SECTIONS.finditer(text))
    if not sections:
        return text.strip(), None
    positive = [text[:sections[0].start()].strip()]
    negative = None
    seen = set()
    for index, section in enumerate(sections):
        end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
        value = text[section.end():end].strip()
        label = section.group("label")
        kind = "negative" if section.group("flag") or label in {"负面", "负面提示词"} else (
            "artist" if label in {"画师", "画师串"} else "positive"
        )
        if kind in seen:
            raise ValueError(f"Duplicate {kind} section")
        seen.add(kind)
        if kind != "negative":
            if negative is not None:
                raise ValueError("Place the negative section last")
            if not value:
                raise ValueError(f"Empty {kind} section")
            positive.append(value)
            continue
        if not value and section.group("flag"):
            raise ValueError('Provide tags after --negative; use --negative "" to clear defaults')
        if value and value[0] in {"\"", "'"}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError("Unclosed quote in negative section")
            value = value[1:-1]
        negative = value
    prompt = ", ".join(part for part in positive if part)
    if not prompt:
        raise ValueError("A positive prompt is required")
    return prompt, negative
