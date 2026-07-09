"""Click command tree for the Python frontend."""

from __future__ import annotations

import sys
from getpass import getpass

import click

from trendpower_tui.config import (
    TrendpowerConfig,
    ModelEntry,
    ensure_trendpower_home_directory,
    ensure_trendpower_home_env,
    get_config_file_path,
    is_trendpower_setup_complete,
    load_config,
    save_config,
)
from trendpower_tui.model_providers import MODEL_PROVIDERS, provider_by_id


@click.group()
def cli() -> None:
    """trendpower command-line utilities."""


@cli.group()
def config() -> None:
    """Manage trendpower configuration."""


@config.group()
def model() -> None:
    """Manage configured models."""


@model.command("list")
def list_models() -> None:
    """List all configured models."""

    ensure_trendpower_home_env()
    if not is_trendpower_setup_complete():
        click.echo("No models configured. Run `trendpower config model add` to add one.")
        return

    config_data = load_config()
    if not config_data.models:
        click.echo("No models configured.")
        return

    default_name = config_data.defaultModel or config_data.models[0].name
    click.echo(f"Default model: {default_name}\n")
    click.echo("Configured models:\n")
    for index, entry in enumerate(config_data.models, start=1):
        suffix = " (default)" if entry.name == default_name else ""
        click.echo(f"  {index}. {entry.name}{suffix}")
        click.echo(f"     provider: {entry.provider}")
        click.echo(f"     baseURL: {entry.baseURL}")
        click.echo(f"     API Key: ****{entry.APIKey[-4:]}")
        click.echo()

    click.echo(
        f"\nThe default model is `{default_name}`. To change the default model, run:\n\n"
        "  trendpower config model set-default <model_name>\n"
    )


@model.command("add")
@click.option("--name", prompt=True, help="Model name to send to the provider.")
@click.option(
    "--provider",
    "provider_id",
    type=click.Choice([provider.id for provider in MODEL_PROVIDERS]),
    default="openai",
    show_default=True,
    help="Provider preset.",
)
@click.option("--base-url", default=None, help="Override provider base URL.")
@click.option("--api-key", default=None, help="API key. If omitted, prompts without echo.")
def add_model(name: str, provider_id: str, base_url: str | None, api_key: str | None) -> None:
    """Add a new model configuration."""

    ensure_trendpower_home_env()
    ensure_trendpower_home_directory()

    provider = provider_by_id(provider_id)
    if provider is None:
        raise click.ClickException(f'Unknown provider "{provider_id}".')

    resolved_base_url = base_url or provider.baseURL
    if not resolved_base_url:
        resolved_base_url = click.prompt("Base URL")
    resolved_api_key = api_key or getpass("API key: ")
    entry = ModelEntry(
        name=name.strip(),
        baseURL=resolved_base_url.strip(),
        APIKey=resolved_api_key.strip(),
        provider=provider.providerType,
    )

    models: list[ModelEntry]
    default_model: str | None = None
    try:
        if is_trendpower_setup_complete():
            config_data = load_config()
            models = list(config_data.models)
            default_model = config_data.defaultModel
        else:
            models = []
    except Exception:
        models = []

    models.append(entry)
    save_config(TrendpowerConfig(models=models, defaultModel=default_model or entry.name))
    click.echo(f'\nModel "{entry.name}" added. Config saved to: {get_config_file_path()}')


@model.command("remove")
@click.argument("model_name", required=False)
def remove_model(model_name: str | None) -> None:
    """Remove a model configuration by name."""

    ensure_trendpower_home_env()
    if not is_trendpower_setup_complete():
        raise click.ClickException("No configuration found. Nothing to remove.")

    config_data = load_config()
    if len(config_data.models) == 1:
        raise click.ClickException("Cannot remove the last model. At least one model must be configured.")

    resolved_name = model_name or _prompt_select_model_name(config_data, "remove")
    models = [entry for entry in config_data.models if entry.name != resolved_name]
    if len(models) == len(config_data.models):
        raise click.ClickException(f'Model "{resolved_name}" not found.')

    default_model = config_data.defaultModel
    if default_model == resolved_name:
        default_model = models[0].name if models else None
    save_config(TrendpowerConfig(models=models, defaultModel=default_model))
    click.echo(f'Model "{resolved_name}" removed.')


@model.command("set-default")
@click.argument("model_name", required=False)
def set_default_model(model_name: str | None) -> None:
    """Set the default model by name."""

    ensure_trendpower_home_env()
    if not is_trendpower_setup_complete():
        raise click.ClickException("No configuration found. Run `trendpower config model add` to add a model first.")

    config_data = load_config()
    resolved_name = model_name or _prompt_select_model_name(config_data, "set as default")
    if all(entry.name != resolved_name for entry in config_data.models):
        raise click.ClickException(f'Model "{resolved_name}" not found.')

    save_config(TrendpowerConfig(models=config_data.models, defaultModel=resolved_name))
    click.echo(f'Default model set to "{resolved_name}".')


@cli.command("diagnose")
@click.option("--model-name", default=None, help="Override which configured model to test. Defaults to defaultModel.")
@click.option("--with-tools", is_flag=True, default=False, help="Also test a single trendpower tool call.")
@click.option("--max-tokens", default=None, type=int, help="Override max_tokens used by the agent path.")
def diagnose(model_name: str | None, with_tools: bool, max_tokens: int | None) -> None:
    """Hit the configured model 3 ways to isolate where trendpower breaks.

    Tier 1: bare ``chat.completions.create`` like the user-provided sample
    script. If this fails, the endpoint itself is the problem.

    Tier 2: same call but streaming with ``stream_options.include_usage`` and
    ``temperature=0`` (what ``OpenAIModelProvider`` actually sends). If Tier 1
    passes but Tier 2 fails, the endpoint dislikes one of those flags.

    Tier 3 (``--with-tools``): adds a single trendpower tool definition. If
    Tier 2 passes but Tier 3 fails, the endpoint does not support tool
    calling and you need a different deployment.
    """

    import asyncio
    import traceback

    ensure_trendpower_home_env()
    if not is_trendpower_setup_complete():
        raise click.ClickException("No configuration found. Run `trendpower config model add` first.")

    config_data = load_config()
    if not config_data.models:
        raise click.ClickException("No models configured.")
    target_name = model_name or config_data.defaultModel or config_data.models[0].name
    entry = next((m for m in config_data.models if m.name == target_name), None)
    if entry is None:
        raise click.ClickException(f"Model '{target_name}' not found in config.")

    click.echo(f"Testing model={entry.name} provider={entry.provider} baseURL={entry.baseURL}")
    click.echo("")

    if entry.provider == "anthropic":
        _diagnose_anthropic(entry)
        return

    # --- Tier 1: raw call mirroring the user-provided sample ---------------
    click.echo("[Tier 1] Bare chat.completions.create (mirrors user sample)")
    try:
        from openai import OpenAI

        client = OpenAI(base_url=entry.baseURL, api_key=entry.APIKey)
        resp = client.chat.completions.create(
            model=entry.name,
            messages=[
                {"role": "system", "content": ""},
                {"role": "user", "content": "ping"},
            ],
        )
        click.echo(f"  OK -> {(resp.choices[0].message.content or '').strip()[:80]}")
    except Exception:
        click.echo("  FAILED:")
        traceback.print_exc()
        click.echo("\nTier 1 failed -> the endpoint itself is unreachable or rejects the request.")
        sys.exit(1)

    # --- Tier 2: streaming with extra flags trendpower actually uses ---------
    click.echo("\n[Tier 2] Streaming + stream_options.include_usage + temperature=0")
    try:
        from openai import OpenAI

        client = OpenAI(base_url=entry.baseURL, api_key=entry.APIKey)
        kwargs: dict = {
            "model": entry.name,
            "messages": [
                {"role": "system", "content": "you are a helpful assistant"},
                {"role": "user", "content": "say hi"},
            ],
            "temperature": 0,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = 16 * 1024
        stream = client.chat.completions.create(**kwargs)
        out: list[str] = []
        for chunk in stream:
            if not chunk.choices:
                continue
            piece = chunk.choices[0].delta.content
            if piece:
                out.append(piece)
        click.echo(f"  OK -> {''.join(out).strip()[:80]}")
    except Exception:
        click.echo("  FAILED:")
        traceback.print_exc()
        click.echo(
            "\nTier 2 failed but Tier 1 passed. Most likely the endpoint rejects one of:\n"
            "  - stream_options.include_usage  (some Ark endpoints)\n"
            "  - temperature=0                  (some reasoning models)\n"
            "  - max_tokens=16384               (try `--max-tokens 4096`)\n"
        )
        sys.exit(1)

    if not with_tools:
        click.echo("\nDone. Re-run with --with-tools to test tool calling support.")
        return

    # --- Tier 3: full trendpower-style request with one tool -----------------
    click.echo("\n[Tier 3] Adding one tool definition (function calling)")
    try:
        from trendpower.community.openai import OpenAIModelProvider
        from trendpower.coding.tools.read_file import read_file_tool
        from trendpower.foundation import Model

        provider = OpenAIModelProvider(base_url=entry.baseURL, api_key=entry.APIKey)
        options = {"max_tokens": max_tokens or 16 * 1024}
        model = Model(entry.name, provider, options)

        async def run() -> None:
            chunks: list[str] = []
            async for snapshot in model.stream(
                {
                    "prompt": "you are a helpful assistant",
                    "messages": [
                        {"role": "user", "content": [{"type": "text", "text": "say hi"}]},
                    ],
                    "tools": [read_file_tool],
                    "signal": None,
                }
            ):
                for part in snapshot.get("content") or []:
                    if isinstance(part, dict) and part.get("type") == "text":
                        chunks.append(part.get("text") or "")
            click.echo(f"  OK -> {''.join(chunks).strip()[:80] or '(no text content)'}")

        asyncio.run(run())
    except Exception:
        click.echo("  FAILED:")
        traceback.print_exc()
        click.echo(
            "\nTier 3 failed but Tier 2 passed. The endpoint likely does NOT support\n"
            "function/tool calling. Try a different Ark deployment that supports tools\n"
            "(DeepSeek V3, doubao 1.5 pro, etc.) and re-add it with trendpower config model add.\n"
        )
        sys.exit(1)

    click.echo("\nAll tiers passed. trendpower should work with this model.")


def _diagnose_anthropic(entry: ModelEntry) -> None:
    import traceback

    click.echo("[Tier 1] Anthropic messages.create")
    try:
        from anthropic import Anthropic

        client = Anthropic(base_url=entry.baseURL or None, api_key=entry.APIKey)
        msg = client.messages.create(
            model=entry.name,
            max_tokens=128,
            messages=[{"role": "user", "content": "ping"}],
        )
        text = "".join(block.text for block in msg.content if hasattr(block, "text"))
        click.echo(f"  OK -> {text.strip()[:80]}")
    except Exception:
        click.echo("  FAILED:")
        traceback.print_exc()
        sys.exit(1)


@cli.group()
def trace() -> None:
    """Inspect agent run traces (written when trendpower_TRACE=1)."""


@trace.command("list")
@click.option("-n", "--limit", default=20, help="Max traces to show.")
def list_traces(limit: int) -> None:
    """List recent agent traces, newest first."""

    from rich.console import Console

    from trendpower_tui.trace import render_trace_index

    Console().print(render_trace_index(limit))


@trace.command("view")
@click.argument("run_id", required=False)
def view_trace(run_id: str | None) -> None:
    """Render a trace as a waterfall. Defaults to the most recent run."""

    from rich.console import Console

    from trendpower_tui.trace import resolve_trace_path, render_trace

    path = resolve_trace_path(run_id)
    if path is None:
        target = run_id or "any run"
        click.echo(f"No trace found for {target}. Try `trendpower trace list`.")
        sys.exit(1)
    console = Console()
    console.print(f"[dim]{path}[/dim]\n")
    console.print(render_trace(path))


def _prompt_select_model_name(config_data: TrendpowerConfig, action_label: str) -> str:
    click.echo(f"Select a model to {action_label}:")
    for index, entry in enumerate(config_data.models, start=1):
        click.echo(f"  {index}. {entry.name}")
    raw = click.prompt("Model number", type=int)
    if raw < 1 or raw > len(config_data.models):
        click.echo("Invalid selection.", err=True)
        sys.exit(1)
    return config_data.models[raw - 1].name
