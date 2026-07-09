"""Middleware that loads skills at run start and injects them into the prompt."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional, Set

from .skill_reader import read_skill_frontmatter
from .types import SkillFrontmatter


def create_skills_middleware(skills_dirs: Optional[List[str]] = None) -> Any:
    if skills_dirs is None:
        skills_dirs = [str(Path.cwd() / "skills")]

    async def before_agent_run(params):  # noqa: ARG001
        skills: List[SkillFrontmatter] = []
        seen: Set[str] = set()

        for skills_dir in skills_dirs:
            if skills_dir.startswith("~"):
                skills_dir = os.path.expanduser(skills_dir)
            root = Path(skills_dir)
            if not root.exists():
                continue
            try:
                folders = list(root.iterdir())
            except OSError:
                continue
            for folder in folders:
                skill_file = folder / "SKILL.md"
                skill_path = str(skill_file)
                if not folder.is_dir():
                    continue
                if skill_path in seen:
                    continue
                if not skill_file.exists():
                    continue
                seen.add(skill_path)
                frontmatter_data = await read_skill_frontmatter(skill_path)
                skills.append(frontmatter_data)

        return {"skills": skills}

    async def before_model(params):
        agent_context = params["agentContext"]
        model_context = params["modelContext"]
        skills = agent_context.get("skills") or []
        if not skills:
            return None

        requested_name = agent_context.get("requestedSkillName")
        requested_skill = None
        if requested_name:
            for sk in skills:
                if sk.get("name", "").lower() == requested_name.lower():
                    requested_skill = sk
                    break

        skills_xml = "\n".join(
            f'<skill name="{sk.get("name", "")}" path="{sk.get("path", "")}">\n{sk.get("description", "")}\n</skill>'
            for sk in skills
        )

        explicit_block = ""
        if requested_skill:
            explicit_block = (
                "<explicit_skill_invocation>\n"
                f'The user explicitly selected the skill "{requested_skill.get("name", "")}" from the slash command picker.\n'
                f'You must read the matching skill file at "{requested_skill.get("path", "")}" before answering.\n'
                "</explicit_skill_invocation>\n"
            )

        addition = (
            "\n\n<skill_system>\n"
            "<instructions>\n"
            "You have access to skills that provide optimized workflows for specific tasks. Each skill contains best practices, frameworks, and references to additional resources.\n\n"
            "**Progressive Loading Pattern:**\n"
            "1. When a user query matches a skill's use case, immediately call `read_file` on the skill's main file using the path attribute provided in the skill tag below\n"
            "2. If an explicit requested skill is provided in the system context, load that skill first even if the user message is short\n"
            "3. Read and understand the skill's workflow and instructions\n"
            "4. The skill file contains references to external resources under the same folder\n"
            "5. Load referenced resources only when needed during execution\n"
            "6. Follow the skill's instructions precisely\n"
            "</instructions>\n\n"
            f"{explicit_block}\n"
            "<skills>\n"
            f"{skills_xml}\n"
            "</skills>\n"
            "</skill_system>"
        )

        return {"prompt": model_context["prompt"] + addition}

    return SimpleNamespace(beforeAgentRun=before_agent_run, beforeModel=before_model)
