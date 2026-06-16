from core.pages_config_service import PagesConfigService


def test_apply_payload_deep_merges_features_and_applies_scalar_sections():
    config = {
        "features": {
            "draw": {"enabled": True, "chain": [{"provider_id": "a"}]},
            "edit": {"enabled": True},
        },
        "debounce_interval": 1,
    }
    payload = {
        "features": {
            "draw": {"enabled": False},
            "video": {"enabled": True},
        },
        "debounce_interval": 3,
        "network": {"proxy_url": "http://127.0.0.1:7890"},
    }

    result = PagesConfigService(config).apply_payload(payload)

    assert result.providers_changed is False
    assert config["features"]["draw"] == {
        "enabled": False,
        "chain": [{"provider_id": "a"}],
    }
    assert config["features"]["video"] == {"enabled": True}
    assert config["debounce_interval"] == 3
    assert config["network"] == {"proxy_url": "http://127.0.0.1:7890"}


def test_apply_payload_normalizes_providers_and_marks_changed():
    config = {}
    payload = {
        "providers": [
            {"id": "gitee", "__type": "gitee_images", "api_keys": ["k"]},
            "bad",
            {"id": "openai", "__template_key": "openai_images", "__type": "ignored"},
        ]
    }

    result = PagesConfigService(config).apply_payload(payload)

    assert result.providers_changed is True
    assert config["providers"] == [
        {"id": "gitee", "api_keys": ["k"], "__template_key": "gitee_images"},
        {"id": "openai", "__template_key": "openai_images"},
    ]


def test_provider_configs_by_id_skips_empty_ids():
    providers = [
        {"id": "a", "model": "x"},
        {"id": "", "model": "ignored"},
        {"model": "ignored"},
    ]

    assert PagesConfigService.provider_configs_by_id(providers) == {
        "a": {"id": "a", "model": "x"}
    }
