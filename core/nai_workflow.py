from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from copy import deepcopy

from .nai_prompt import translate_nai_prompt

NAI_TEMPLATES = {"nai_native", "nai_gateway", "nai_openai_images"}
_LABEL = re.compile(r"(?<!\S)(画师串|画师|正面|提示词|tags|负面提示词|负面|negative)\s*[:：]", re.I)


def is_nai_provider(provider: dict) -> bool:
    if provider.get("__template_key") in NAI_TEMPLATES:
        return True
    model = str(provider.get("model") or "").lower()
    return provider.get("__template_key") in {"openai_images"} and (
        "nai" in model or "novelai" in model or bool(provider.get("nai_translate_prompt"))
    )


def parse_nai_input(text: str) -> dict[str, str]:
    text = str(text or "").strip()
    sections = list(_LABEL.finditer(text))
    result = {"artist": "", "tags": text, "negative": ""}
    if not sections:
        return result
    result["tags"] = text[:sections[0].start()].strip()
    seen = set()
    for index, match in enumerate(sections):
        label = match.group(1).lower()
        key = "artist" if label in {"画师", "画师串", "artist"} else (
            "negative" if label in {"负面", "负面提示词", "negative"} else "tags"
        )
        if key in seen:
            raise ValueError("NAI 提示词分区重复")
        seen.add(key)
        end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
        value = text[match.end():end].strip()
        result[key] = ", ".join(filter(None, [result[key], value])) if key == "tags" else value
    return result


def looks_like_tags(text: str) -> bool:
    text = str(text or "").strip()
    if not text or re.search(r"[\u3400-\u9fff。！？]", text):
        return False
    parts = [part.strip() for part in re.split(r"[,，\n]", text) if part.strip()]
    if any(len(part.split()) > 7 for part in parts):
        return False
    # Conservative: prose and ambiguous single words go through review.
    return len(parts) >= 2 or bool(re.search(r"(?:artist:|\b[1-9](?:girl|boy)s?\b|\bsolo\b)", text))


def compose_nai_prompt(artist: str, tags: str, prefix: str = "") -> str:
    return ", ".join(value.strip(" ,\n") for value in (prefix, artist, tags) if value.strip(" ,\n"))


def provider_fingerprint(provider: dict) -> str:
    return hashlib.sha256(json.dumps(provider, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class NaiWorkflow:
    """Conversion never submits an image; confirmation consumes an exact draft once."""
    def __init__(self):
        self.pending: dict[tuple[str, str], dict] = {}
        self.preparing: dict[tuple[str, str], str] = {}

    def begin(self, key: tuple[str, str]) -> str:
        if key not in self.preparing and len(self.preparing) >= 1000:
            raise ValueError("NAI 转换任务过多，请稍后重试")
        self.pending.pop(key, None)
        token = secrets.token_hex(8)
        self.preparing[key] = token
        return token

    def finish(self, key: tuple[str, str], token: str) -> bool:
        if self.preparing.get(key) != token:
            return False
        self.preparing.pop(key, None)
        return True

    async def prepare(self, context, text: str, provider: dict, umo: str, *, force=False, llm_id="") -> dict:
        if not is_nai_provider(provider):
            raise ValueError("请选择 NAI 服务商模板")
        if not text.strip() or len(text) > 8000:
            raise ValueError("NAI 描述不能为空且不能超过 8000 字")
        fields = parse_nai_input(text)
        if not fields["tags"]:
            raise ValueError("请填写正面 Tag 或自然语言描述")
        settings = dict(provider)
        if llm_id:
            settings["nai_llm_provider_id"] = llm_id
        converted = force or not looks_like_tags(fields["tags"])
        if converted:
            fields["tags"] = await translate_nai_prompt(context, fields["tags"], settings, umo)
        # Artists are supplied explicitly or prefilled, never guessed by the LLM.
        inline_artist = bool(re.search(r"artist\s*:", fields["tags"], re.I))
        fields["artist"] = fields["artist"] or ("" if inline_artist else str(provider.get("nai_artist") or "").strip())
        if not any(m.group(1).lower() in {"负面", "负面提示词", "negative"} for m in _LABEL.finditer(text)):
            fields["negative"] = str(provider.get("negative_prompt") or "").strip()
        fields.update(prefix=str(provider.get("nai_prompt_prefix") or "").strip(), converted=converted)
        fields["prompt"] = compose_nai_prompt(fields["artist"], fields["tags"], fields["prefix"])
        if len(fields["prompt"]) > 16000:
            raise ValueError("NAI Tag 过长")
        return fields

    def remember(self, key: tuple[str, str], draft: dict, provider: dict) -> dict:
        now = time.monotonic()
        self.pending = {k: v for k, v in self.pending.items() if v["expires"] > now}
        if len(self.pending) >= 1000:
            raise ValueError("待确认 NAI 草稿过多，请稍后重试")
        item = {**deepcopy(draft), "token": secrets.token_hex(4), "expires": now + 900,
                "provider_fingerprint": provider_fingerprint(provider)}
        self.pending[key] = item
        return deepcopy(item)

    def consume(self, key: tuple[str, str], token: str, provider: dict) -> dict:
        item = self.pending.get(key)
        if not item or item["expires"] <= time.monotonic():
            self.pending.pop(key, None)
            raise ValueError("没有有效的待确认 NAI 草稿，请重新发送 /nai 描述")
        if not secrets.compare_digest(str(token), item["token"]):
            raise ValueError("确认编号不匹配，请使用最近一份草稿的编号")
        if item["provider_fingerprint"] != provider_fingerprint(provider):
            self.pending.pop(key, None)
            raise ValueError("服务商配置已变化，请重新转换并确认")
        return self.pending.pop(key)
