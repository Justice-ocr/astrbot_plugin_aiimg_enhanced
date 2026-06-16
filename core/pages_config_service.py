from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SCALAR_CONFIG_KEYS = (
    "storage",
    "debounce_interval",
    "max_user_concurrency",
    "max_user_video_concurrency",
    "network",
    "reply_config",
)


@dataclass(frozen=True)
class PagesConfigApplyResult:
    providers_changed: bool = False


class PagesConfigService:
    """Applies Settings page payloads to the plugin config."""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @staticmethod
    def normalize_provider(provider: dict[str, Any]) -> dict[str, Any]:
        cleaned = {key: value for key, value in provider.items() if key != "__type"}
        if "__template_key" not in cleaned and "__type" in provider:
            cleaned["__template_key"] = provider["__type"]
        return cleaned

    @staticmethod
    def provider_configs_by_id(providers: list[Any]) -> dict[str, dict[str, Any]]:
        return {
            str(provider.get("id") or "").strip(): provider
            for provider in providers
            if isinstance(provider, dict) and str(provider.get("id") or "").strip()
        }

    def apply_payload(self, data: dict[str, Any]) -> PagesConfigApplyResult:
        providers_changed = False

        if "features" in data and isinstance(data["features"], dict):
            cfg_features = self.config.setdefault("features", {})
            for feature_key, feature_value in data["features"].items():
                if isinstance(feature_value, dict) and isinstance(cfg_features.get(feature_key), dict):
                    cfg_features[feature_key].update(feature_value)
                else:
                    cfg_features[feature_key] = feature_value

        for key in SCALAR_CONFIG_KEYS:
            if key in data:
                self.config[key] = data[key]

        if "providers" in data and isinstance(data["providers"], list):
            self.config["providers"] = [
                self.normalize_provider(provider)
                for provider in data["providers"]
                if isinstance(provider, dict)
            ]
            providers_changed = True

        return PagesConfigApplyResult(providers_changed=providers_changed)
