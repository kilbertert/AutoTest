## trendpower

trendpower is a small library for building **ReAct-style** agent loops, implemented in Python.

The repository contains three Python packages plus a shared skills directory:

- `trendpower-py/` — the core agent loop library (`trendpower` package)
- `trendpower-tui/` — a Textual-based Terminal UI on top of `trendpower` (`trendpower_tui` package)
- `trendpower-web/` — a terminal REPL + live browser visualization of the prompt sent to the LLM each turn (`trendpower_web` package)
- `skills/` — bundled skills (repo root) loaded by the agent at runtime

### Package dependencies

Dependencies are **one-directional** — each package depends only on the ones to its right, never the reverse:

```
trendpower-web  ──depends──▶  trendpower-tui  ──depends──▶  trendpower  (trendpower-py)
 (trendpower_web)              (trendpower_tui)              (core lib, no upstream deps)
```

- `trendpower` (core) depends on no sibling package; it is usable on its own (see `trendpower-py/examples/`).
- `trendpower-tui` depends on `trendpower` — it is only UI + event bridging; the agent loop, tools, and providers all live in core. Core does not know the TUI exists.
- `trendpower-web` depends on both `trendpower` and `trendpower-tui` — it reuses TUI components and adds instrumented providers that broadcast each LLM request to the browser.

MCP is split along the same principle: the reusable protocol client lives in core (`trendpower/community/mcp/*`), while process-specific glue (config-path resolution, lifecycle, the `/mcp` command) lives in the frontend (`trendpower_tui/mcp/*`), which imports from core.

A full startup-to-answer trace lives in `docs/execution-flow.md`.

## trendpower-py — core library

Four layers, plus a `community` area for third-party integrations.

### 1) `foundation`

Core primitives that everything else builds on:

- **Models**: the `Model` abstraction and provider-facing contracts.
- **Messages**: a single transcript type that flows end-to-end through the system.
- **Tools**: tool definitions and execution plumbing (the "actions" an agent can invoke).

Files: `trendpower-py/trendpower/foundation/{models,messages,tools}/*`

Design intent:

- Keep these types stable and reusable.
- Prefer adding new backends by extending `ModelProvider`.
- Keep `Message` as the single source of truth for the conversation transcript.

### 2) `agent`

A reusable **ReAct-style agent loop**:

- Maintains state over a conversation transcript.
- Chooses between "think / act / observe" style steps.
- Orchestrates tool calls and feeds observations back into the next reasoning step.

Files:
- `trendpower-py/trendpower/agent/agent.py`
- `trendpower-py/trendpower/agent/agent_middleware.py`
- `trendpower-py/trendpower/agent/skills/*` (skill system middleware)

This layer should depend only on `foundation`, and remain generic (not coding-specific).

### 3) `coding`

A layer for coding-specific agents and tools.

- **Leading Agent**: `trendpower-py/trendpower/coding/agents/lead_agent.py`
- **Tools**: `trendpower-py/trendpower/coding/tools/*`, including `bash`, `read_file`, `write_file`, `str_replace`, `list_files`, `glob_search`, `grep_search`, `apply_patch`, `file_info`, `mkdir`, `move_path`

### 4) `community`

In-repo integrations live under `trendpower-py/trendpower/community/*`.

- Treat these as optional adapters over `foundation` interfaces.
- Avoid coupling `foundation`/`agent` to integrations.

Current integrations:

- `community/openai`: `OpenAIModelProvider` backed by the `openai` SDK.
- `community/anthropic`: `AnthropicModelProvider` backed by the `anthropic` SDK.

## trendpower-tui — Terminal UI

Built with **Textual** (Python's analogue of Ink/React).

- `trendpower-tui/trendpower_tui/app.py` — Textual `App` entry point
- `trendpower-tui/trendpower_tui/tui/*` — widgets, screens, theming
- `trendpower-tui/trendpower_tui/commands/*` — slash-command handlers
- `trendpower-tui/trendpower_tui/config/*`, `settings/*` — config and persisted settings
- `trendpower-tui/trendpower_tui/sessions/*` — conversation persistence; transcripts are saved to `$TRENDPOWER_HOME/sessions/<id>.json` after each completed turn and reloaded via `/resume`
- `trendpower-tui/trendpower_tui/model_providers.py` — provider wiring for the TUI
- `trendpower-tui/trendpower_tui/tui/skill_paths.py` — discovers skill directories (cwd, `TRENDPOWER_HOME`, `~/.{agents,trendpower}/skills`, repo ancestors, package-relative)

The TUI installs as a console script: `trendpower` (see `trendpower-tui/pyproject.toml`).

## Skills

Skill system for enhancing agent capabilities:

- Skills live under `skills/` at the **repo root**, each as a folder containing a `SKILL.md` definition with frontmatter. They are not part of any Python package (not shipped in the wheel).
- The skills middleware (`trendpower-py/trendpower/agent/skills/skills_middleware.py`) loads them at agent-run start and injects them into the system prompt via a `<skill_system>` block.
- The TUI uses `skill_paths.discover_skills_dirs()` to locate skills, in order: (1) `TRENDPOWER_SKILLS_DIR` if set, used exclusively; (2) `<cwd>/skills` and the nearest ancestor `skills/`; (3) a `skills/` found by walking up from the installed `trendpower_tui`/`trendpower` package location. With an **editable** install (`uv tool install --editable`) step 3 resolves back to the source checkout, so the repo-root `skills/` is discovered with zero config and edits show up live (no env var, no reinstall).

Current skills:
- `coding-plan` — read-only plan-mode workflow for coding tasks
- `deep-research-plan` — read-and-search-only plan-mode workflow for research/article tasks
- `frontend-design` — frontend design workflow

## Stack

- **Language / runtime**: Python ≥ 3.10
- **Build backend**: Hatchling
- **Core deps** (`trendpower-py`): `openai`, `anthropic`, `pydantic`, `python-frontmatter`, `aiofiles`
- **TUI deps** (`trendpower-tui`): `textual`, `rich`, `click`, `pydantic`, `pyyaml`
- **Tests**: `pytest` with `pytest-asyncio` (asyncio mode = auto)

## Conventions

- Keep comments minimal and intent-focused.
- Avoid drive-by refactors outside the task at hand.
- API style is **async-first** (mirrors the original TS `AsyncGenerator` pattern).
- Tool parameter schemas use **pydantic**.
- File ops use **pathlib + aiofiles**.
- Subprocess uses **asyncio.create_subprocess_exec**.
- Cancellation uses a custom `AbortSignal` class.
- Provider options: `OpenAIModelProvider` merges `Model.options` into `chat.completions.create` (provider-specific flags allowed). Defaults include `temperature: 0` and `top_p: 0`.
- Agent loop: when an assistant message contains tool calls, tools are invoked in parallel and their results are appended as `tool_result` messages before continuing.

## Commands

```bash
# Core library
cd trendpower-py
pip install -e ".[dev]"
pytest

# TUI
cd trendpower-tui
pip install -e .
trendpower              # launches the Textual TUI
```

## Testing

Tests use **pytest** with `pytest-asyncio` in `asyncio_mode = "auto"` (configured in `trendpower-py/pyproject.toml`). Discover-and-run via `pytest` from inside the package directory.

**Where to put tests:** Prefer **co-located** unit tests next to the code under test (e.g. `trendpower/.../tests/test_foo.py` or `test_foo.py` beside `foo.py`). A top-level `tests/` tree is fine for integration suites and large fixtures.

**What must be tested:** Not everything. Unit tests are encouraged for pure logic, non-trivial algorithms, and regressions, but are not a blanket requirement for every change. Use judgment.

