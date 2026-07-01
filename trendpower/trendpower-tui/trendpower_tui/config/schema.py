"""Pydantic schemas matching ``src/cli/config/schema.ts``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ProviderType = Literal["openai", "anthropic"]


class ModelEntry(BaseModel):
    """A single configured model endpoint."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    baseURL: str = Field(min_length=1)
    APIKey: str = Field(min_length=1)
    provider: ProviderType = "openai"


class TrendpowerConfig(BaseModel):
    """Top-level ``~/.trendpower/config.yaml`` schema."""

    model_config = ConfigDict(extra="forbid")

    models: list[ModelEntry] = Field(min_length=1)
    defaultModel: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def default_model_must_exist(self) -> "TrendpowerConfig":
        if self.defaultModel and all(model.name != self.defaultModel for model in self.models):
            raise ValueError(f'defaultModel "{self.defaultModel}" does not match any configured model name')
        return self
