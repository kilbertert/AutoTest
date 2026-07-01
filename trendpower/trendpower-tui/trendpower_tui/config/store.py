"""Read/write helpers for ``~/.trendpower/config.yaml``."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

import yaml

from .schema import TrendpowerConfig

DEFAULT_REL = ".trendpower"
CONFIG_FILENAME = "config.yaml"


def get_default_trendpower_home() -> Path:
    """Return the default config home used when ``TRENDPOWER_HOME`` is unset."""

    return Path.home() / DEFAULT_REL


def ensure_trendpower_home_env() -> None:
    """Set ``TRENDPOWER_HOME`` to the default path if it is currently unset."""

    if not os.environ.get("TRENDPOWER_HOME", "").strip():
        os.environ["TRENDPOWER_HOME"] = str(get_default_trendpower_home())


def get_trendpower_home_path() -> Path:
    """Resolve ``TRENDPOWER_HOME``.

    This mirrors the TS implementation, where callers are expected to call
    ``ensure_trendpower_home_env`` before accessing the path.
    """

    value = os.environ.get("TRENDPOWER_HOME", "").strip()
    if not value:
        raise RuntimeError("TRENDPOWER_HOME is not set")
    return Path(value).expanduser().resolve()


def get_config_file_path() -> Path:
    return get_trendpower_home_path() / CONFIG_FILENAME


def ensure_trendpower_home_directory() -> None:
    get_trendpower_home_path().mkdir(parents=True, exist_ok=True)


def is_trendpower_setup_complete() -> bool:
    home = get_trendpower_home_path()
    return home.is_dir() and get_config_file_path().exists()


def load_config() -> TrendpowerConfig:
    raw = get_config_file_path().read_text(encoding="utf-8")
    parsed: Any = yaml.safe_load(raw)
    return TrendpowerConfig.model_validate(parsed)


def save_config(config: TrendpowerConfig | dict[str, Any]) -> None:
    validated = TrendpowerConfig.model_validate(config)
    target = get_config_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(
        validated.model_dump(exclude_none=True),
        sort_keys=False,
        allow_unicode=True,
        width=10**9,
    )

    fd, tmp_name = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".tmp", dir=target.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        tmp_path.replace(target)
    finally:
        with suppress(OSError):
            tmp_path.unlink()
