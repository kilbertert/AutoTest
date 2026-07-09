// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

// Message types for webview ↔ extension host communication.
//
// Direction A (web → ext): commands triggered by webview UI.
// Direction B (ext → web): events emitted by the runner, surfaced to webview.

"use strict";

// ─── Direction A: webview → extension ────────────────────────────────────

export type WebviewCommand =
  | { command: "webviewLoaded" }
  | { command: "runHealthCheck" }
  | { command: "submitPrompt"; prompt: string; resumeFrom?: string; skill?: string }
  | { command: "cancelRun" }
  | { command: "openExternalUrl"; url: string }
  | { command: "openTrendpowerHome" };

// ─── Direction B: extension → webview ────────────────────────────────────

export interface HealthUpdate {
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

export interface RunnerStarted {
  runId: string;
  prompt: string;
  startedAt: number;
}

export type RunnerEvent =
  | { kind: "status"; phase: string; detail?: string }
  | { kind: "thinking"; text: string }
  | { kind: "tool_call"; id: string; name: string; input: unknown }
  | { kind: "tool_result"; toolCallId: string; name: string; output: string; isError: boolean; elapsedMs: number }
  | { kind: "assistant_text"; text: string }
  | { kind: "assistant_final"; text: string }
  | { kind: "progress"; done: number; total: number; failed: number; module?: string }
  | { kind: "module_status"; module: string; state: "pending" | "running" | "passed" | "failed" }
  | { kind: "error"; message: string; trace?: string };

export interface RunnerEnded {
  runId: string;
  ok: boolean;
  durationMs: number;
  reason?: "completed" | "cancelled" | "error";
}

export type ExtensionMessage =
  | { command: "healthUpdate"; health: HealthUpdate }
  | { command: "runnerStarted"; info: RunnerStarted }
  | { command: "runnerEvent"; runId: string; event: RunnerEvent }
  | { command: "runnerEnded"; info: RunnerEnded };