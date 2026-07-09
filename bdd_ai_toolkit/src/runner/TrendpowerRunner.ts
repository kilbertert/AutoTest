// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

// TrendpowerRunner spawns the headless Python runner and parses NDJSON events.
//
// Lifecycle:
//   idle → starting → running → (stopping →) stopped | error
//
// On stop():
//   1. SIGTERM the child
//   2. After 5s, SIGKILL if still alive
//   3. The runner.py handles asyncio.CancelledError and emits session_end
//
// On unexpected child exit before session_end:
//   Emit a synthetic error event + runnerEnded{ok:false, reason:"error"}.

"use strict";

import { spawn, ChildProcessWithoutNullStreams } from "child_process";
import * as path from "path";
import * as os from "os";
import * as fs from "fs";
import * as vscode from "vscode";
import { RunnerEvent, RunnerStarted, RunnerEnded } from "./protocol";

export type RunnerState = "idle" | "starting" | "running" | "stopping" | "stopped" | "error";

export interface RunnerOutput {
  state: RunnerState;
  started?: RunnerStarted;
  event?: RunnerEvent;
  ended?: RunnerEnded;
}

export class TrendpowerRunner {
  private child: ChildProcessWithoutNullStreams | null = null;
  private state: RunnerState = "idle";
  private runId: string = "";
  private startedAt = 0;
  private currentRunListeners: Array<(o: RunnerOutput) => void> = [];
  private stderrBuf = "";
  private lineBuf = "";

  constructor(private readonly extensionPath: string) {}

  getState(): RunnerState {
    return this.state;
  }

  /** Subscribe to events from the current run. Returns an unsubscribe fn. */
  subscribe(listener: (o: RunnerOutput) => void): () => void {
    this.currentRunListeners.push(listener);
    return () => {
      this.currentRunListeners = this.currentRunListeners.filter((l) => l !== listener);
    };
  }

  private emit(out: RunnerOutput) {
    for (const l of this.currentRunListeners) {
      try { l(out); } catch { /* swallow listener errors */ }
    }
  }

  /** Start a new run. Returns immediately; events stream via subscribe(). */
  async start(prompt: string, cwd: string, opts?: { resumeFrom?: string; skill?: string }): Promise<void> {
    if (this.state === "running" || this.state === "starting") {
      throw new Error("runner is already active; call stop() first");
    }

    const runnerPy = this.resolveRunnerPath();
    if (!fs.existsSync(runnerPy)) {
      this.state = "error";
      this.emit({
        state: this.state,
        event: { kind: "error", message: `runner.py not found at ${runnerPy}. Run "npm run compile" first.` },
        ended: { runId: "", ok: false, durationMs: 0, reason: "error" },
      });
      return;
    }

    this.state = "starting";
    // On resume, keep the same run id so the checkpoint filename matches.
    this.runId = opts?.resumeFrom || newRunId();
    this.startedAt = Date.now();
    this.stderrBuf = "";
    this.lineBuf = "";
    this.currentRunListeners = [];

    // `uv run --project <trendpower-py>` so the runner inherits the trendpower
    // venv (where `import trendpower.community.mcp` works). A bare
    // `uv run --no-project` from the workspace cwd would shadow `trendpower`
    // with the repo's `trendpower/skills/` namespace and fail with
    // "No module named 'trendpower.community'".
    const trendpowerPy = path.resolve(this.extensionPath, "..", "..", "trendpower", "trendpower-py");
    const useProject = fs.existsSync(path.join(trendpowerPy, "pyproject.toml"));
    const uvArgs: string[] = useProject
      ? ["run", "--project", trendpowerPy, "python", runnerPy, "--prompt", prompt, "--cwd", cwd]
      : ["run", "--no-project", "python", runnerPy, "--prompt", prompt, "--cwd", cwd];

    // Stable run id → checkpoint filename. Pass through so resume + new runs
    // share the same id slot.
    uvArgs.push("--run-id", this.runId);
    if (opts?.resumeFrom) {
      uvArgs.push("--resume", opts.resumeFrom);
    }
    if (opts?.skill) {
      uvArgs.push("--skill", opts.skill);
    }

    let proc: ChildProcessWithoutNullStreams;
    try {
      proc = spawn("uv", uvArgs, {
        cwd,
        env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
        shell: false,
        windowsHide: true,
      });
    } catch (e) {
      this.state = "error";
      this.emit({
        state: this.state,
        event: { kind: "error", message: `failed to spawn uv: ${e instanceof Error ? e.message : String(e)}` },
        ended: { runId: this.runId, ok: false, durationMs: 0, reason: "error" },
      });
      return;
    }

    this.child = proc;
    this.state = "running";

    const started: RunnerStarted = {
      runId: this.runId,
      prompt,
      startedAt: this.startedAt,
    };
    this.emit({ state: this.state, started });

    proc.stdout.setEncoding("utf-8");
    proc.stdout.on("data", (chunk: string) => this.handleStdout(chunk));

    proc.stderr.setEncoding("utf-8");
    proc.stderr.on("data", (chunk: string) => {
      this.stderrBuf += chunk;
      if (this.stderrBuf.length > 16 * 1024) {
        this.stderrBuf = this.stderrBuf.slice(-16 * 1024);
      }
    });

    proc.on("error", (err) => {
      this.state = "error";
      this.emit({
        state: this.state,
        event: {
          kind: "error",
          message: `runner process error: ${err.message}`,
          trace: this.stderrBuf.slice(-2000),
        },
        ended: { runId: this.runId, ok: false, durationMs: Date.now() - this.startedAt, reason: "error" },
      });
      this.child = null;
    });

    proc.on("close", (code, signal) => {
      // If runner.py emitted a clean session_end, the ended event has already been emitted.
      // If not, synthesize one.
      const isActive = this.state === "running" || this.state === "starting";
      if (isActive) {
        const wasCancelled = signal === "SIGTERM";
        this.state = wasCancelled ? "stopped" : "error";
        this.emit({
          state: this.state,
          event: wasCancelled
            ? { kind: "status", phase: "cancelled", detail: `runner terminated by ${signal}` }
            : { kind: "error", message: `runner exited unexpectedly (code=${code}, signal=${signal})`, trace: this.stderrBuf.slice(-2000) },
          ended: {
            runId: this.runId,
            ok: wasCancelled,
            durationMs: Date.now() - this.startedAt,
            reason: wasCancelled ? "cancelled" : "error",
          },
        });
      }
      this.child = null;
    });
  }

  private handleStdout(chunk: string): void {
    // NDJSON: split on \n, parse each non-empty line.
    this.lineBuf += chunk;
    let nlIdx = this.lineBuf.indexOf("\n");
    while (nlIdx >= 0) {
      const line = this.lineBuf.slice(0, nlIdx).trim();
      this.lineBuf = this.lineBuf.slice(nlIdx + 1);
      if (line) this.parseLine(line);
      nlIdx = this.lineBuf.indexOf("\n");
    }
    if (this.lineBuf.length > 64 * 1024) {
      // a single unterminated line is too long; flush and warn
      this.lineBuf = "";
      this.emit({
        state: this.state,
        event: { kind: "error", message: "runner stdout: line exceeded 64KB, discarded" },
      });
    }
  }

  private parseLine(line: string): void {
    let obj: any;
    try {
      obj = JSON.parse(line);
    } catch {
      // not JSON — surface as raw status for debug visibility
      this.emit({ state: this.state, event: { kind: "status", phase: "raw", detail: line.slice(0, 400) } });
      return;
    }
    const t = obj.type;
    if (t === "session_end") {
      this.state = obj.ok ? "stopped" : "error";
      const ended: RunnerEnded = {
        runId: obj.run_id ?? this.runId,
        ok: !!obj.ok,
        durationMs: typeof obj.duration_ms === "number" ? obj.duration_ms : Date.now() - this.startedAt,
        reason: obj.ok ? "completed" : "error",
      };
      this.emit({ state: this.state, ended });
      return;
    }
    if (t === "error") {
      this.emit({ state: this.state, event: { kind: "error", message: String(obj.message ?? "unknown"), trace: obj.trace } });
      return;
    }
    if (t === "status") {
      this.emit({ state: this.state, event: { kind: "status", phase: String(obj.phase ?? ""), detail: obj.detail } });
      return;
    }
    if (t === "thinking") {
      this.emit({ state: this.state, event: { kind: "thinking", text: String(obj.text ?? "") } });
      return;
    }
    if (t === "tool_call") {
      this.emit({
        state: this.state,
        event: { kind: "tool_call", id: String(obj.id ?? ""), name: String(obj.name ?? ""), input: obj.input },
      });
      return;
    }
    if (t === "tool_result") {
      this.emit({
        state: this.state,
        event: {
          kind: "tool_result",
          toolCallId: String(obj.tool_call_id ?? ""),
          name: String(obj.name ?? ""),
          output: String(obj.output ?? ""),
          isError: !!obj.is_error,
          elapsedMs: typeof obj.elapsed_ms === "number" ? obj.elapsed_ms : 0,
        },
      });
      return;
    }
    if (t === "assistant_text") {
      this.emit({ state: this.state, event: { kind: "assistant_text", text: String(obj.text ?? "") } });
      return;
    }
    if (t === "assistant_final") {
      this.emit({ state: this.state, event: { kind: "assistant_final", text: String(obj.text ?? "") } });
      return;
    }
    if (t === "progress") {
      this.emit({
        state: this.state,
        event: {
          kind: "progress",
          done: Number(obj.done ?? 0),
          total: Number(obj.total ?? 0),
          failed: Number(obj.failed ?? 0),
          module: typeof obj.module === "string" ? obj.module : undefined,
        },
      });
      return;
    }
    if (t === "module_status") {
      const rawState = String(obj.state ?? "pending");
      const state: "pending" | "running" | "passed" | "failed" =
        rawState === "running" || rawState === "passed" || rawState === "failed" ? rawState : "pending";
      this.emit({
        state: this.state,
        event: { kind: "module_status", module: String(obj.module ?? ""), state },
      });
      return;
    }
    if (t === "session_start") {
      // already surfaced via RunnerStarted; ignore duplicate
      return;
    }
    // unknown event — surface as raw
    this.emit({ state: this.state, event: { kind: "status", phase: "raw", detail: JSON.stringify(obj).slice(0, 400) } });
  }

  /** Request graceful stop. SIGTERM, then SIGKILL after 5s. */
  async stop(): Promise<void> {
    if (!this.child || (this.state !== "running" && this.state !== "starting")) {
      return;
    }
    this.state = "stopping";
    try { this.child.kill("SIGTERM"); } catch { /* ignore */ }
    const deadline = Date.now() + 5000;
    while (this.child && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 100));
    }
    if (this.child) {
      try { this.child.kill("SIGKILL"); } catch { /* ignore */ }
    }
  }

  private resolveRunnerPath(): string {
    // extensionPath/resources/trendpower-headless/runner.py
    return path.join(this.extensionPath, "resources", "trendpower-headless", "runner.py");
  }
}

function newRunId(): string {
  // 12-char hex, matches the runner.py format
  return Math.random().toString(16).slice(2, 14).padEnd(12, "0");
}

// Helper: get a sane cwd for the runner. Falls back to homedir if no workspace.
export function resolveRunnerCwd(workspaceFolder: vscode.WorkspaceFolder | undefined): string {
  if (workspaceFolder) return workspaceFolder.uri.fsPath;
  return os.homedir();
}