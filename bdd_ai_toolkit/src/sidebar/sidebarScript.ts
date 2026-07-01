// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.
//
// Webview-side script. Runs in a sandboxed iframe with VS Code's CSP.
// Communicates with the extension host via acquireVsCodeApi().postMessage().
//
// Compiled to out/src/sidebar/sidebarScript.js, then copied to
// out/resources/sidebar/sidebar.js by scripts/compile.js so the webview
// can load it via the asWebviewUri() URL.

declare function acquireVsCodeApi(): {
  postMessage(message: any): void;
  getState(): any;
  setState(state: any): void;
};

const vscode = acquireVsCodeApi();

interface HealthUpdate {
  uv: boolean;
  uvVersion?: string;
  trendpower: boolean;
  trendpowerVersion?: string;
  mcpServers: number;
  model: string | null;
  provider: string | null;
  configPath: string;
  errors: string[];
}

interface RunnerStarted {
  runId: string;
  prompt: string;
  startedAt: number;
}

type RunnerEvent =
  | { kind: "status"; phase: string; detail?: string }
  | { kind: "thinking"; text: string }
  | { kind: "tool_call"; id: string; name: string; input: unknown }
  | { kind: "tool_result"; toolCallId: string; name: string; output: string; isError: boolean; elapsedMs: number }
  | { kind: "assistant_text"; text: string }
  | { kind: "assistant_final"; text: string }
  | { kind: "error"; message: string; trace?: string };

interface RunnerEnded {
  runId: string;
  ok: boolean;
  durationMs: number;
  reason?: "completed" | "cancelled" | "error";
}

// ─── DOM refs ──────────────────────────────────────────────────────────

const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} not found`);
  return el as T;
};

const promptEl = $<HTMLTextAreaElement>("prompt");
const btnRun = $<HTMLButtonElement>("btn-run");
const btnStop = $<HTMLButtonElement>("btn-stop");
const btnClear = $<HTMLButtonElement>("btn-clear");
const badgeUv = $<HTMLSpanElement>("badge-uv");
const badgeTp = $<HTMLSpanElement>("badge-tp");
const badgeMcp = $<HTMLSpanElement>("badge-mcp");
const errorsEl = $<HTMLDivElement>("errors");
const logEl = $<HTMLDivElement>("log");
const statusEl = $<HTMLDivElement>("status");
const linkHome = $<HTMLAnchorElement>("link-home");

// ─── State ─────────────────────────────────────────────────────────────

let isRunning = false;

// ─── Init ──────────────────────────────────────────────────────────────

window.addEventListener("load", () => {
  vscode.postMessage({ command: "webviewLoaded" });
});

btnRun.addEventListener("click", () => {
  if (isRunning) return;
  const prompt = promptEl.value.trim();
  if (!prompt) return;
  vscode.postMessage({ command: "submitPrompt", prompt });
});

btnStop.addEventListener("click", () => {
  vscode.postMessage({ command: "cancelRun" });
});

btnClear.addEventListener("click", () => {
  logEl.innerHTML = "";
  setStatus("idle", "");
});

promptEl.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    btnRun.click();
  }
});

linkHome.addEventListener("click", (e) => {
  e.preventDefault();
  vscode.postMessage({ command: "openTrendpowerHome" });
});

// ─── Inbound messages ─────────────────────────────────────────────────

window.addEventListener("message", (event) => {
  const msg = event.data;
  if (!msg || typeof msg !== "object") return;
  switch (msg.command) {
    case "healthUpdate":     onHealth(msg.health as HealthUpdate); break;
    case "runnerStarted":    onRunnerStarted(msg.info as RunnerStarted); break;
    case "runnerEvent":      onRunnerEvent(msg.event as RunnerEvent); break;
    case "runnerEnded":      onRunnerEnded(msg.info as RunnerEnded); break;
    case "prefillPrompt":    promptEl.value = String(msg.prompt ?? ""); break;
  }
});

// ─── Handlers ─────────────────────────────────────────────────────────

function onHealth(h: HealthUpdate): void {
  setBadge(badgeUv, h.uv, h.uv ? `uv: ${h.uvVersion ?? "ok"}` : "uv: missing");
  setBadge(badgeTp, h.trendpower, h.trendpower ? `trendpower: ${h.trendpowerVersion ?? "ok"}` : "trendpower: missing");
  const mcpText = h.mcpServers > 0 ? `mcp: ${h.mcpServers} server${h.mcpServers === 1 ? "" : "s"}` : "mcp: none";
  setBadge(badgeMcp, h.mcpServers > 0, mcpText);

  if (h.errors.length > 0) {
    errorsEl.hidden = false;
    errorsEl.textContent = h.errors.join("\n");
  } else {
    errorsEl.hidden = true;
    errorsEl.textContent = "";
  }

  // Enable Run only if uv + trendpower are usable. MCP is informational.
  btnRun.disabled = !(h.uv && h.trendpower);
}

function onRunnerStarted(info: RunnerStarted): void {
  isRunning = true;
  btnRun.disabled = true;
  btnStop.disabled = false;
  setStatus(`running… (${info.runId})`, "");
  appendRow({ kind: "status", phase: "started", detail: `prompt: ${info.prompt.slice(0, 80)}` });
}

function onRunnerEvent(ev: RunnerEvent): void {
  if (ev.kind === "assistant_text" || ev.kind === "assistant_final") {
    // collapse consecutive assistant_text into a single row that updates in place
    upsertAssistantRow(ev);
    return;
  }
  appendRow(ev);
}

function onRunnerEnded(info: RunnerEnded): void {
  isRunning = false;
  btnRun.disabled = false;
  btnStop.disabled = true;
  const reason = info.reason ?? (info.ok ? "completed" : "error");
  const text = info.ok
    ? `done in ${(info.durationMs / 1000).toFixed(1)}s (${reason})`
    : `failed in ${(info.durationMs / 1000).toFixed(1)}s (${reason})`;
  setStatus(text, info.ok ? "ok" : "bad");
}

// ─── DOM helpers ──────────────────────────────────────────────────────

function setBadge(el: HTMLElement, ok: boolean, text: string): void {
  el.textContent = text;
  el.classList.remove("ok", "bad", "warn");
  el.classList.add(ok ? "ok" : "bad");
}

function setStatus(text: string, cls: "" | "ok" | "bad"): void {
  statusEl.textContent = text;
  statusEl.classList.remove("ok", "bad");
  if (cls) statusEl.classList.add(cls);
}

let assistantRow: HTMLDivElement | null = null;
let assistantBuffer = "";

function upsertAssistantRow(ev: { kind: "assistant_text" | "assistant_final"; text: string }): void {
  if (!assistantRow) {
    assistantRow = document.createElement("div");
    assistantRow.className = `tp-row ${ev.kind}`;
    const head = document.createElement("div");
    head.className = "tp-row-head";
    const kindEl = document.createElement("span");
    kindEl.className = "tp-row-kind";
    kindEl.textContent = ev.kind === "assistant_final" ? "assistant" : "assistant";
    head.appendChild(kindEl);
    const body = document.createElement("div");
    body.className = "tp-row-body";
    body.textContent = "";
    assistantRow.appendChild(head);
    assistantRow.appendChild(body);
    logEl.appendChild(assistantRow);
    assistantBuffer = "";
  }
  assistantBuffer += ev.text;
  const body = assistantRow.querySelector(".tp-row-body") as HTMLDivElement;
  body.textContent = assistantBuffer;
  logEl.scrollTop = logEl.scrollHeight;
  if (ev.kind === "assistant_final") {
    assistantRow = null;
    assistantBuffer = "";
  }
}

function appendRow(ev: RunnerEvent): void {
  const row = document.createElement("div");
  row.className = `tp-row ${ev.kind}`;
  const head = document.createElement("div");
  head.className = "tp-row-head";
  const kindEl = document.createElement("span");
  kindEl.className = "tp-row-kind";
  kindEl.textContent = ev.kind;
  head.appendChild(kindEl);
  if ("name" in ev && ev.name) {
    const nameEl = document.createElement("span");
    nameEl.className = "tp-row-name";
    nameEl.textContent = String(ev.name);
    head.appendChild(nameEl);
  }
  if ("phase" in ev && ev.phase) {
    const phaseEl = document.createElement("span");
    phaseEl.className = "tp-row-phase";
    phaseEl.textContent = String(ev.phase);
    head.appendChild(phaseEl);
  }
  row.appendChild(head);

  const body = document.createElement("div");
  body.className = "tp-row-body";
  let bodyText = "";
  switch (ev.kind) {
    case "thinking":
      bodyText = ev.text;
      break;
    case "status":
      bodyText = ev.detail ?? "";
      break;
    case "tool_call":
      try { bodyText = JSON.stringify(ev.input, null, 2); } catch { bodyText = String(ev.input); }
      break;
    case "tool_result":
      bodyText = ev.output;
      break;
    case "error":
      bodyText = ev.message + (ev.trace ? "\n" + ev.trace : "");
      break;
  }
  body.textContent = bodyText;
  row.appendChild(body);

  logEl.appendChild(row);
  logEl.scrollTop = logEl.scrollHeight;
}