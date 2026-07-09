from __future__ import annotations

from typing import TypedDict


class SkillFrontmatter(TypedDict, total=False):
    name: str
    description: str
    path: str
