"""Known provider presets for config commands and bootstrap flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ProviderType = Literal["openai", "anthropic"]


@dataclass(frozen=True)
class ModelProviderConfig:
    label: str
    id: str
    baseURL: str
    providerType: ProviderType


MODEL_PROVIDERS: list[ModelProviderConfig] = [
    ModelProviderConfig("Anthropic (Claude)", "anthropic", "https://api.anthropic.com", "anthropic"),
    ModelProviderConfig("OpenAI", "openai", "https://api.openai.com/v1", "openai"),
    ModelProviderConfig("Volcengine - General", "volcengine", "https://ark.cn-beijing.volces.com/api/v3", "openai"),
    ModelProviderConfig(
        "Volcengine - Coding Plan",
        "volcengine_coding_plan",
        "https://ark.cn-beijing.volces.com/api/coding/v3",
        "openai",
    ),
    ModelProviderConfig("Qwen (Aliyun)", "qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1", "openai"),
    ModelProviderConfig("Minimax (Domestic)", "minimax_cn", "https://api.minimaxi.com/v1", "openai"),
    ModelProviderConfig("Minimax (Global)", "minimax_global", "https://api.minimax.io/v1", "openai"),
    ModelProviderConfig(
        "Minimax (Anthropic-compatible)",
        "minimax",
        "https://api.minimaxi.com/anthropic",
        "anthropic",
    ),
    ModelProviderConfig("GLM (Zhipu AI)", "glm", "https://open.bigmodel.cn/api/paas/v4", "openai"),
    ModelProviderConfig("Kimi (Moonshot)", "kimi", "https://api.moonshot.cn/v1", "openai"),
    ModelProviderConfig("DeepSeek (OpenAI compatible)", "deepseek", "https://api.deepseek.com/v1", "openai"),
    ModelProviderConfig("Other", "other", "", "openai"),
]


def provider_by_id(provider_id: str) -> ModelProviderConfig | None:
    return next((provider for provider in MODEL_PROVIDERS if provider.id == provider_id), None)
