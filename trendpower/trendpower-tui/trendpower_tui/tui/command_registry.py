"""Slash command registry for built-ins and skills."""

from __future__ import annotations

from dataclasses import dataclass

from trendpower.agent.skills.list_skills import list_skills


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    type: str


@dataclass(frozen=True)
class BuiltinInvocation:
    name: str
    args: str


@dataclass(frozen=True)
class PromptSubmission:
    text: str
    requested_skill_name: str | None


BUILTIN_COMMANDS = [
    SlashCommand("clear", "Clear the current conversation history", "builtin"),
    SlashCommand("copy", "Copy the whole conversation transcript to the clipboard", "builtin"),
    SlashCommand("exit", "Exit the TUI session", "builtin"),
    SlashCommand("export", "Write the conversation transcript to a file (`/export [path]`)", "builtin"),
    SlashCommand("help", "List available slash commands, or show details for one (`/help <name>`)", "builtin"),
    SlashCommand("mcp", "Manage MCP servers: `/mcp list` to inspect, `/mcp reload` to reconnect", "builtin"),
    SlashCommand("model", "Manage configured models: list, switch default, add or remove", "builtin"),
    SlashCommand("quit", "Exit the TUI session", "builtin"),
    SlashCommand("resume", "Resume a previously saved conversation (`/resume` to pick, `/resume <id>`)", "builtin"),
]


async def load_available_commands(skills_dirs: list[str] | None = None) -> list[SlashCommand]:
    skills = await list_skills(skills_dirs)
    skill_commands = sorted(
        (
            SlashCommand(
                name=skill.get("name", ""),
                description=skill.get("description", ""),
                type="skill",
            )
            for skill in skills
            if skill.get("name")
        ),
        key=lambda command: command.name.lower(),
    )
    return _dedupe_commands([*BUILTIN_COMMANDS, *skill_commands])


def filter_commands(commands: list[SlashCommand], query: str) -> list[SlashCommand]:
    normalized = _normalize_command_name(query)
    if not normalized:
        return commands
    matches = [
        command
        for command in commands
        if normalized in command.name.lower() or normalized in command.description.lower()
    ]
    return sorted(matches, key=lambda command: _score_command_match(command, normalized), reverse=True)


def resolve_builtin_command(text: str) -> BuiltinInvocation | None:
    trimmed = text.strip()
    if not trimmed:
        return None
    token, _, args = trimmed.partition(" ")
    name = _normalize_command_name(token)
    if any(command.name == name for command in BUILTIN_COMMANDS):
        return BuiltinInvocation(name=name, args=args.strip())
    return None


def format_help(commands: list[SlashCommand], target: str | None = None) -> str:
    if target:
        normalized = _normalize_command_name(target)
        match = next((command for command in commands if command.name.lower() == normalized), None)
        if match is None:
            return f"Unknown command: `/{target}`. Run `/help` to see available commands."
        kind = "Built-in command" if match.type == "builtin" else "Skill"
        return f"**/{match.name}** - _{kind}_\n\n{match.description}"

    builtins = [command for command in commands if command.type == "builtin"]
    skills = [command for command in commands if command.type == "skill"]
    lines = ["**Available slash commands**", ""]
    if builtins:
        lines.append("_Built-in_")
        lines.extend(f"- `/{command.name}` - {command.description}" for command in builtins)
    if skills:
        if builtins:
            lines.append("")
        lines.append("_Skills_")
        lines.extend(f"- `/{command.name}` - {command.description}" for command in skills)
    lines.extend(["", "Run `/help <name>` for details on a single command."])
    return "\n".join(lines)


def build_prompt_submission(text: str, commands: list[SlashCommand]) -> PromptSubmission:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return PromptSubmission(text=text, requested_skill_name=None)
    token = stripped.split(None, 1)[0]
    command_name = _normalize_command_name(token)
    skill = next(
        (command for command in commands if command.type == "skill" and command.name.lower() == command_name),
        None,
    )
    return PromptSubmission(text=text, requested_skill_name=skill.name if skill else None)


def _dedupe_commands(commands: list[SlashCommand]) -> list[SlashCommand]:
    seen: set[str] = set()
    deduped: list[SlashCommand] = []
    for command in commands:
        key = command.name.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(command)
    return deduped


def _normalize_command_name(value: str) -> str:
    return value.removeprefix("/").strip().lower()


def _score_command_match(command: SlashCommand, query: str) -> int:
    name = command.name.lower()
    description = command.description.lower()
    if name.startswith(query):
        return 3
    if query in name:
        return 2
    if query in description:
        return 1
    return 0
