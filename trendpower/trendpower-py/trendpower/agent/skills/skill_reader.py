"""Read a SKILL.md file and parse its YAML frontmatter."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from .types import SkillFrontmatter


async def read_skill_frontmatter(path: str) -> SkillFrontmatter:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File {path} does not exist")
    content = p.read_text(encoding="utf-8")
    parsed = frontmatter.loads(content)
    data: dict = dict(parsed.metadata)
    data["path"] = path
    return data  # type: ignore[return-value]
