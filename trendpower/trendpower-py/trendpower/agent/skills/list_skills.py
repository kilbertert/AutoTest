"""Enumerate skills under one or more skill directories."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Set

from .skill_reader import read_skill_frontmatter
from .types import SkillFrontmatter


async def list_skills(skills_dirs: Optional[List[str]] = None) -> List[SkillFrontmatter]:
    if skills_dirs is None:
        skills_dirs = [str(Path.cwd() / "skills")]

    skills: List[SkillFrontmatter] = []
    seen: Set[str] = set()

    for skills_dir in skills_dirs:
        if skills_dir.startswith("~"):
            skills_dir = os.path.expanduser(skills_dir)
        root = Path(skills_dir)
        if not root.exists():
            continue
        try:
            entries = sorted(root.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for folder in entries:
            if not folder.is_dir():
                continue
            skill_file = folder / "SKILL.md"
            skill_path = str(skill_file)
            if skill_path in seen:
                continue
            if not skill_file.exists():
                continue
            seen.add(skill_path)
            frontmatter_data = await read_skill_frontmatter(skill_path)
            skills.append(frontmatter_data)
    return skills
