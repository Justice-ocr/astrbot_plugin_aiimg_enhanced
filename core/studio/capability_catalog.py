from __future__ import annotations

from copy import deepcopy
from typing import Any


SUPPORT_VALUES = {"supported", "unsupported", "unknown"}
IMAGE_MEDIA_TYPES = ["image/jpeg", "image/png", "image/webp"]
VERIFIED_DATE = "2026-09-22"


_PROTOCOLS: dict[str, tuple[str, str]] = {
    "xai_video": ("xai-videos-v1", VERIFIED_DATE),
    "openai_video": ("openai-compatible-videos", VERIFIED_DATE),
    "minimax_h3_video": ("minimax-video-generation-v2", VERIFIED_DATE),
    "agnes_video": ("agnes-videos-v1", VERIFIED_DATE),
    "openai_images": ("openai-compatible-images", VERIFIED_DATE),
    "openai_full_url_images": ("openai-compatible-images-full-url", VERIFIED_DATE),
    "openai_chat": ("openai-compatible-chat-images", VERIFIED_DATE),
    "gemini_openai_images": ("openai-compatible-images", VERIFIED_DATE),
    "gemini_openai_chat": ("openai-compatible-chat-images", VERIFIED_DATE),
    "grok_images": ("xai-images", VERIFIED_DATE),
    "grok_images_edit": ("xai-images", VERIFIED_DATE),
    "grok_chat": ("xai-chat-images", VERIFIED_DATE),
    "grok2api_images": ("grok2api-images", VERIFIED_DATE),
    "gemini_native": ("gemini-native-images", VERIFIED_DATE),
    "flow2api": ("flow2api-images", VERIFIED_DATE),
    "vertex_ai_anonymous": ("vertex-anonymous-images", VERIFIED_DATE),
    "gitee_images": ("gitee-images", VERIFIED_DATE),
    "gitee_async": ("gitee-async-images", VERIFIED_DATE),
    "jimeng": ("jimeng-images", VERIFIED_DATE),
    "nai_native": ("novelai-native-compatible", VERIFIED_DATE),
    "nai_gateway": ("novelai-get-gateway", VERIFIED_DATE),
    "modelscope_openai_images": ("openai-compatible-images", VERIFIED_DATE),
    "grok_video": ("legacy-grok-video", VERIFIED_DATE),
    "grok2api_video": ("grok2api-video", VERIFIED_DATE),
    "flow2api_video": ("flow2api-video", VERIFIED_DATE),
    "custom_video": ("custom-video", VERIFIED_DATE),
}

_IMAGE_TEMPLATES = {
    "nai_native",
    "nai_gateway",
    "openai_images",
    "openai_full_url_images",
    "openai_chat",
    "gemini_native",
    "flow2api",
    "vertex_ai_anonymous",
    "grok_images",
    "grok_images_edit",
    "grok_chat",
    "grok2api_images",
    "gemini_openai_images",
    "gemini_openai_chat",
    "gitee_images",
    "gitee_async",
    "jimeng",
    "modelscope_openai_images",
}

_VIDEO_TEMPLATES = {
    "xai_video",
    "agnes_video",
    "minimax_h3_video",
    "openai_video",
    "grok_video",
    "grok2api_video",
    "flow2api_video",
    "custom_video",
}

_IMAGE_EDIT_DEFAULTS = {
    "nai_native": True,
    "nai_gateway": False,
    "openai_images": True,
    "openai_full_url_images": True,
    "openai_chat": True,
    "gemini_native": True,
    "flow2api": True,
    "vertex_ai_anonymous": True,
    "grok_images": True,
    "grok_images_edit": True,
    "grok_chat": True,
    "grok2api_images": True,
    "gemini_openai_images": True,
    "gemini_openai_chat": True,
    "gitee_images": False,
    "gitee_async": True,
    "jimeng": True,
    "modelscope_openai_images": False,
}

_STREAMING_IMAGE_TEMPLATES = {
    "openai_chat",
    "grok_chat",
    "gemini_openai_chat",
}

_EXPLICIT_ROOT_KEYS = {
    "operations",
    "references",
    "parameters",
    "streaming",
    "cancellation",
    "protocol",
}


def _support(value: Any, default: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    return text if text in SUPPORT_VALUES else default


def _integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _enum_parameter(values: list[str], default: Any = "") -> dict[str, Any]:
    clean_values = [str(value) for value in values if str(value).strip()]
    return {
        "status": "supported" if clean_values else "unknown",
        "values": clean_values,
        "default": str(default or ""),
    }


def _range_parameter(minimum: int, maximum: int, default: Any) -> dict[str, Any]:
    return {
        "status": "supported",
        "minimum": minimum,
        "maximum": maximum,
        "default": _integer(default, minimum),
        "unit": "seconds",
    }


def _reference_mode(
    mode_id: str,
    label: str,
    minimum: int,
    maximum: int,
    *,
    status: str = "supported",
    resolutions: list[str] | None = None,
    duration: tuple[int, int] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": mode_id,
        "label": label,
        "status": _support(status),
        "min_images": minimum,
        "max_images": maximum,
        "accepted_media_types": list(IMAGE_MEDIA_TYPES),
    }
    if resolutions is not None:
        item["resolutions"] = list(resolutions)
    if duration is not None:
        item["duration"] = {
            "minimum": duration[0],
            "maximum": duration[1],
            "unit": "seconds",
        }
    return item


def _base(provider: dict[str, Any], template_key: str) -> dict[str, Any]:
    protocol_id, verified = _PROTOCOLS.get(
        template_key, ("unclassified", "")
    )
    return {
        "provider_id": str(provider.get("id") or "").strip(),
        "label": str(provider.get("label") or provider.get("id") or "").strip(),
        "model": str(provider.get("model") or "").strip(),
        "template_key": template_key,
        "source": "template",
        "protocol": {
            "id": protocol_id,
            "last_verified": verified,
        },
        "operations": {
            "image_generate": "unknown",
            "image_edit": "unknown",
            "video_generate": "unknown",
        },
        "references": {
            "status": "unknown",
            "active_mode": "",
            "modes": [],
        },
        "parameters": {
            "duration": {"status": "unknown"},
            "aspect_ratios": {"status": "unknown", "values": [], "default": ""},
            "sizes": {"status": "unknown", "values": [], "default": ""},
            "resolutions": {"status": "unknown", "values": [], "default": ""},
        },
        "streaming": {
            "image_generate": "unknown",
            "image_edit": "unknown",
            "video_generate": "unknown",
        },
        "cancellation": {
            "local": "supported",
            "upstream": "unknown",
        },
    }


def _apply_image_capabilities(
    result: dict[str, Any], provider: dict[str, Any], template_key: str
) -> None:
    result["operations"]["image_generate"] = (
        "unsupported" if template_key == "gitee_async" else "supported"
    )
    default_edit = _IMAGE_EDIT_DEFAULTS.get(template_key, False)
    supports_edit = bool(provider.get("supports_edit", default_edit))
    if template_key in {"nai_gateway", "gitee_images", "modelscope_openai_images"}:
        supports_edit = False
    result["operations"]["image_edit"] = (
        "supported" if supports_edit else "unsupported"
    )
    result["operations"]["video_generate"] = "unsupported"
    stream_status = (
        "supported" if template_key in _STREAMING_IMAGE_TEMPLATES else "unsupported"
    )
    result["streaming"]["image_generate"] = stream_status
    result["streaming"]["image_edit"] = (
        stream_status if supports_edit else "unsupported"
    )
    result["streaming"]["video_generate"] = "unsupported"
    result["cancellation"]["upstream"] = "unsupported"

    default_size = str(
        provider.get("default_size") or provider.get("default_resolution") or ""
    ).strip()
    result["parameters"]["sizes"] = {
        "status": "unknown",
        "values": [],
        "default": default_size,
    }

    if not supports_edit:
        result["references"] = {
            "status": "unsupported",
            "active_mode": "",
            "modes": [],
        }
        return

    if template_key == "nai_native":
        active_mode = str(provider.get("nai_reference_mode") or "img2img")
        modes = [
            _reference_mode("img2img", "重绘", 1, 1),
            _reference_mode("character", "角色参考", 1, 1),
            _reference_mode("vibe", "Vibe 参考", 1, 9),
        ]
    else:
        active_mode = "reference_images"
        modes = [_reference_mode("reference_images", "参考图", 1, 9)]
    result["references"] = {
        "status": "supported",
        "active_mode": active_mode,
        "modes": modes,
    }


def _apply_xai_video(result: dict[str, Any], provider: dict[str, Any]) -> None:
    model = str(provider.get("model") or "").strip()
    text_resolutions = ["480p", "720p"]
    if model == "grok-imagine-video-1.5":
        text_resolutions.append("1080p")
    active_mode = str(provider.get("xai_reference_mode") or "reference")
    result["references"] = {
        "status": "supported",
        "active_mode": active_mode,
        "modes": [
            _reference_mode(
                "text", "无参考图", 0, 0,
                resolutions=text_resolutions, duration=(1, 15),
            ),
            _reference_mode(
                "image", "首帧图", 1, 1,
                resolutions=text_resolutions, duration=(1, 15),
            ),
            _reference_mode(
                "reference", "多图参考", 1, 7,
                resolutions=["480p", "720p"], duration=(1, 15),
            ),
        ],
    }
    result["parameters"]["duration"] = _range_parameter(
        1, 15, provider.get("duration", 8)
    )
    result["parameters"]["aspect_ratios"] = _enum_parameter(
        ["auto", "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"],
        provider.get("aspect_ratio", "16:9"),
    )
    result["parameters"]["resolutions"] = _enum_parameter(
        text_resolutions if active_mode != "reference" else ["480p", "720p"],
        provider.get("xai_resolution", "720p"),
    )


def _apply_openai_video(result: dict[str, Any], provider: dict[str, Any]) -> None:
    request_mode = str(provider.get("request_mode") or "auto").strip().lower()
    active_mode = str(provider.get("image_input_mode") or "auto").strip().lower()
    input_reference_status = "unsupported" if request_mode == "json" else "supported"
    result["references"] = {
        "status": "supported",
        "active_mode": active_mode,
        "modes": [
            _reference_mode(
                "input_reference", "文件参考图", 1, 1,
                status=input_reference_status,
            ),
            _reference_mode("image_urls", "参考图 URL", 1, 9),
            _reference_mode("first_last_frame", "首尾帧", 2, 2),
            _reference_mode("roles_reference", "带角色参考图", 1, 9),
            _reference_mode("roles_frames", "带角色首尾帧", 2, 2),
        ],
    }
    result["parameters"]["duration"] = _range_parameter(
        1, 15, provider.get("seconds", 4)
    )
    configured_size = str(provider.get("size") or "").strip()
    result["parameters"]["sizes"] = {
        "status": "unknown",
        "values": [configured_size] if configured_size else [],
        "default": configured_size,
    }
    resolution = str(provider.get("video_resolution") or "").strip().lower()
    result["parameters"]["resolutions"] = {
        "status": "unknown",
        "values": [resolution] if resolution else [],
        "default": resolution,
    }


def _apply_minimax_video(result: dict[str, Any], provider: dict[str, Any]) -> None:
    result["references"] = {
        "status": "supported",
        "active_mode": "auto",
        "modes": [
            _reference_mode(
                "text", "无参考图", 0, 0,
                resolutions=["480p", "768p"], duration=(1, 15),
            ),
            _reference_mode(
                "reference_images", "多图参考", 1, 9,
                resolutions=["480p", "768p", "1080p"], duration=(1, 10),
            ),
            _reference_mode(
                "first_last_frame", "首尾帧", 2, 2,
                resolutions=["480p", "768p"], duration=(1, 10),
            ),
        ],
    }
    result["parameters"]["duration"] = _range_parameter(
        1, 15, provider.get("duration", 5)
    )
    result["parameters"]["aspect_ratios"] = _enum_parameter(
        ["16:9", "9:16", "1:1"], provider.get("ratio", "16:9")
    )
    result["parameters"]["resolutions"] = _enum_parameter(
        ["480p", "768p", "1080p"], provider.get("resolution", "480p")
    )


def _apply_agnes_video(result: dict[str, Any], provider: dict[str, Any]) -> None:
    result["references"] = {
        "status": "supported",
        "active_mode": "auto",
        "modes": [
            _reference_mode("text", "无参考图", 0, 0, duration=(4, 12)),
            _reference_mode("keyframe", "关键帧", 1, 1, duration=(4, 12)),
            _reference_mode("reference_images", "多图参考", 2, 5, duration=(4, 12)),
        ],
    }
    result["parameters"]["duration"] = _range_parameter(
        4, 12, provider.get("seconds", 5)
    )
    result["parameters"]["aspect_ratios"] = _enum_parameter(
        ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
        provider.get("aspect_ratio", "16:9"),
    )


def _apply_video_capabilities(
    result: dict[str, Any], provider: dict[str, Any], template_key: str
) -> None:
    result["operations"] = {
        "image_generate": "unsupported",
        "image_edit": "unsupported",
        "video_generate": "supported",
    }
    result["streaming"] = {
        "image_generate": "unsupported",
        "image_edit": "unsupported",
        "video_generate": "unsupported",
    }
    result["cancellation"]["upstream"] = (
        "unknown" if template_key == "custom_video" else "unsupported"
    )

    if template_key == "xai_video":
        _apply_xai_video(result, provider)
    elif template_key == "openai_video":
        _apply_openai_video(result, provider)
    elif template_key == "minimax_h3_video":
        _apply_minimax_video(result, provider)
    elif template_key == "agnes_video":
        _apply_agnes_video(result, provider)


def _apply_explicit_declaration(
    result: dict[str, Any], provider: dict[str, Any]
) -> None:
    explicit = provider.get("studio_capabilities")
    if not isinstance(explicit, dict):
        explicit = provider.get("capabilities")
    if not isinstance(explicit, dict):
        return
    for key in _EXPLICIT_ROOT_KEYS:
        if key in explicit:
            result[key] = deepcopy(explicit[key])
    result["source"] = "template+explicit"

    operations = result.get("operations")
    if isinstance(operations, dict):
        for key in ("image_generate", "image_edit", "video_generate"):
            operations[key] = _support(operations.get(key))


def build_provider_capability(provider: dict[str, Any]) -> dict[str, Any]:
    item = provider if isinstance(provider, dict) else {}
    template_key = str(
        item.get("__template_key")
        or item.get("template_key")
        or item.get("__type")
        or ""
    ).strip()
    result = _base(item, template_key)
    if template_key in _IMAGE_TEMPLATES:
        _apply_image_capabilities(result, item, template_key)
    elif template_key in _VIDEO_TEMPLATES:
        _apply_video_capabilities(result, item, template_key)
    _apply_explicit_declaration(result, item)
    return result


def build_provider_capabilities(providers: list[Any]) -> list[dict[str, Any]]:
    return [
        build_provider_capability(provider)
        for provider in providers
        if isinstance(provider, dict) and str(provider.get("id") or "").strip()
    ]
