from core.studio.capability_catalog import build_provider_capability


def _modes(capability):
    return {item["id"]: item for item in capability["references"]["modes"]}


def test_video_templates_keep_distinct_reference_and_resolution_rules():
    xai = build_provider_capability({
        "id": "xai",
        "__template_key": "xai_video",
        "model": "grok-imagine-video-1.5",
        "xai_reference_mode": "reference",
    })
    assert _modes(xai)["image"]["max_images"] == 1
    assert _modes(xai)["reference"]["max_images"] == 7
    assert _modes(xai)["reference"]["resolutions"] == ["480p", "720p"]
    assert "1080p" not in xai["parameters"]["resolutions"]["values"]

    openai = build_provider_capability({
        "id": "openai",
        "__template_key": "openai_video",
        "request_mode": "json",
    })
    assert _modes(openai)["input_reference"]["status"] == "unsupported"
    assert _modes(openai)["first_last_frame"]["min_images"] == 2
    assert _modes(openai)["roles_frames"]["max_images"] == 2

    minimax = build_provider_capability({
        "id": "minimax",
        "__template_key": "minimax_h3_video",
    })
    assert _modes(minimax)["reference_images"]["max_images"] == 9
    assert _modes(minimax)["reference_images"]["resolutions"][-1] == "1080p"
    assert _modes(minimax)["first_last_frame"]["resolutions"] == ["480p", "768p"]


def test_unknown_and_custom_templates_are_conservative_without_declaration():
    custom = build_provider_capability({
        "id": "custom",
        "__template_key": "custom_video",
    })
    assert custom["operations"]["video_generate"] == "supported"
    assert custom["references"]["status"] == "unknown"

    unknown = build_provider_capability({
        "id": "mystery",
        "__template_key": "vendor_specific",
        "model": "video-image-everything-pro",
    })
    assert set(unknown["operations"].values()) == {"unknown"}

    declared = build_provider_capability({
        "id": "declared",
        "__template_key": "custom_video",
        "studio_capabilities": {
            "references": {
                "status": "supported",
                "active_mode": "reference_images",
                "modes": [{
                    "id": "reference_images",
                    "label": "参考图",
                    "status": "supported",
                    "min_images": 1,
                    "max_images": 3,
                    "accepted_media_types": ["image/png"],
                }],
            }
        },
    })
    assert declared["source"] == "template+explicit"
    assert declared["references"]["modes"][0]["max_images"] == 3
