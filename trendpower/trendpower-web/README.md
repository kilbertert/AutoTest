# trendpower-web

Run the **same Textual TUI as `trendpower`**, with a parallel web page that
shows **the exact prompt sent to the LLM** on every turn — system prompt
(with skills injected), full message history, tool JSON schemas, and
provider options like `temperature` / `max_tokens` / `thinking`.

## Why

Debugging an agent is mostly "what does the LLM actually see?" Neither
the TUI nor the bare examples surface the real provider request body.
`trendpower-web` captures it right before the SDK call and broadcasts it
over SSE to a static page.

## Install

```bash
uv tool install ./trendpower-web --with ./trendpower-py --with ./trendpower-tui --python 3.12
```

It reads the same `~/.trendpower/config.yaml`, skill directories, settings,
and approval state as `trendpower`.

## Use

```bash
trendpower-web                 # default: http://127.0.0.1:8765
trendpower-web --port 9000
trendpower-web --host 0.0.0.0  # let other devices on the LAN attach
```

The terminal **is** the trendpower TUI — same keybindings, same `/help` and
`/model` slash commands, same approval bar. The only visual change is a
status line saying `[trendpower-web] live view at http://...`.

Open the URL in a browser. Each user turn appears in the browser as:

- **LLM request panel** — the exact kwargs handed to
  `chat.completions.create(**...)` or `messages.create(**...)`: `model`,
  `system`, `messages`, `tools`, `temperature`, `max_tokens`, `thinking`, …
- **Timeline panel** — assistant text, `tool_use` (name + input),
  `tool_result` (truncated snippet), `progress` events, in order

No browser open? The TUI runs normally — `publish` is a no-op with zero
subscribers. Multiple browser tabs can attach to the same TUI and watch.

## How it works

Before booting Textual, three monkey-patches are installed:

1. `trendpower.community.openai.OpenAIModelProvider` and
   `trendpower.community.anthropic.AnthropicModelProvider` are replaced with
   subclasses that publish `llm_request` (the real `_base_params()` dict)
   and `llm_response_chunk` (each streaming snapshot) to the broadcaster.
2. `trendpower_tui.tui.agent_runner.AgentRunner.submit` is wrapped so every
   agent event (`message` / `progress`) is broadcast in addition to being
   posted as a Textual `Message`.
3. `trendpowerApp.on_mount` is extended (via `trendpowerWebApp(trendpowerApp)`) to
   start an aiohttp server on the same asyncio loop Textual is using.

Nothing in `trendpower-py` or `trendpower-tui` is modified — both packages
work unchanged when `trendpower-web` isn't installed.

## SSE event types

| `type`               | When                                                   | Payload                                 |
| -------------------- | ------------------------------------------------------ | --------------------------------------- |
| `user_input`         | A user submits text in the TUI                         | `text`                                  |
| `llm_request`        | About to call the SDK                                  | `provider`, `mode`, `request_id`, `payload` (the real kwargs dict) |
| `llm_response_chunk` | Each streaming snapshot from the SDK                   | `provider`, `request_id`, `snapshot`    |
| `agent_event`        | Every event yielded by `agent.stream()` (mirrored)     | `event` (the raw `AgentEvent` dict)     |

All events also carry `seq` (monotonically increasing) and `ts`.
