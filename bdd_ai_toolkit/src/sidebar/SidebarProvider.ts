// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

// Sidebar webview provider for the Trendpower shell.
//
// Owns the active TrendpowerRunner instance and forwards its events to the
// webview. The webview sends commands back via postMessage.

"use strict";

import * as vscode from "vscode";
import * as path from "path";
import * as os from "os";
import * as fs from "fs";
import { TrendpowerRunner, RunnerOutput, resolveRunnerCwd } from "../runner/TrendpowerRunner";
import { probeHealth } from "../runner/TrendpowerHealth";
import { ExtensionMessage, HealthUpdate, RunnerEvent } from "../runner/protocol";

export class SidebarProvider implements vscode.WebviewViewProvider {
  static readonly viewType = "trendpower-shell.sidebar";

  private view?: vscode.WebviewView;
  private runner?: TrendpowerRunner;
  private currentRunId = "";

  constructor(private readonly context: vscode.ExtensionContext) {}

  resolveWebviewView(webviewView: vscode.WebviewView): void {
    this.view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this.sidebarResourceRoot()],
    };
    webviewView.webview.html = this.renderHtml(webviewView.webview);

    webviewView.webview.onDidReceiveMessage(
      (msg) => this.handleWebviewMessage(msg).catch((e) => this.postError(String(e))),
      undefined,
      this.context.subscriptions,
    );
  }

  /** Open (or focus) the sidebar — exposed as a command. */
  static async openSidebar(): Promise<void> {
    await vscode.commands.executeCommand("workbench.view.trendpower-shell");
    await vscode.commands.executeCommand(`${SidebarProvider.viewType}.focus`);
  }

  /** Run a prompt programmatically (from command palette / keybinding). */
  async runPromptFromCommand(): Promise<void> {
    const view = this.view;
    if (!view) {
      await SidebarProvider.openSidebar();
    }
    const input = await vscode.window.showInputBox({
      prompt: "Prompt to run in trendpower",
      placeHolder: "e.g. 看看 Apifox Tikhub 项目里有哪些 health 相关的接口",
    });
    if (!input || !input.trim()) return;
    (this.view ?? view)?.webview.postMessage({ command: "prefillPrompt", prompt: input } as any);
  }

  /** Cancel the in-flight run, if any. */
  cancelRun(): void {
    this.runner?.stop().catch(() => { /* swallow */ });
  }

  // ─── internals ───────────────────────────────────────────────────────────

  private sidebarResourceRoot(): vscode.Uri {
    return vscode.Uri.file(path.join(this.context.extensionPath, "resources"));
  }

  private renderHtml(webview: vscode.Webview): string {
    const nonce = randomNonce();
    const resourcesDir = path.join(this.context.extensionPath, "resources");
    const stylesUri = webview.asWebviewUri(vscode.Uri.file(path.join(resourcesDir, "sidebar", "styles.css")));
    const scriptUri = webview.asWebviewUri(vscode.Uri.file(path.join(resourcesDir, "sidebar", "sidebar.js")));
    const tmplPath = path.join(resourcesDir, "sidebar", "sidebar.html");
    let tmpl = fs.readFileSync(tmplPath, "utf-8");
    return tmpl
      .replace(/\$\{nonce\}/g, nonce)
      .replace(/\$\{stylesUri\}/g, stylesUri.toString())
      .replace(/\$\{scriptUri\}/g, scriptUri.toString());
  }

  private async handleWebviewMessage(msg: any): Promise<void> {
    switch (msg?.command) {
      case "webviewLoaded":
        await this.runHealthCheck();
        return;
      case "runHealthCheck":
        await this.runHealthCheck();
        return;
      case "submitPrompt":
        await this.startRun(String(msg.prompt ?? ""), {
          resumeFrom: typeof msg.resumeFrom === "string" ? msg.resumeFrom : undefined,
          skill: typeof msg.skill === "string" ? msg.skill : undefined,
        });
        return;
      case "cancelRun":
        await this.runner?.stop();
        return;
      case "openExternalUrl":
        if (typeof msg.url === "string") {
          await vscode.env.openExternal(vscode.Uri.parse(msg.url));
        }
        return;
      case "openTrendpowerHome":
        await vscode.env.openExternal(
          vscode.Uri.file(path.join(os.homedir(), ".trendpower")),
        );
        return;
    }
  }

  private async runHealthCheck(): Promise<void> {
    const health = await probeHealth();
    this.post({ command: "healthUpdate", health });
  }

  private async startRun(prompt: string, opts?: { resumeFrom?: string; skill?: string }): Promise<void> {
    const view = this.view;
    if (!view) return;
    const trimmed = prompt.trim();
    if (!trimmed) {
      this.post({ command: "runnerEnded", info: { runId: "", ok: false, durationMs: 0, reason: "error" } });
      return;
    }
    if (this.runner && (this.runner.getState() === "running" || this.runner.getState() === "starting")) {
      this.postError("runner already active; press Stop first");
      return;
    }

    this.runner = new TrendpowerRunner(this.context.extensionPath);
    // On resume, adopt the runner's run id (== resumeFrom) so events line up.
    this.currentRunId = opts?.resumeFrom || newRunId();
    const unsub = this.runner.subscribe((out) => this.handleRunnerOutput(out));

    const cwd = resolveRunnerCwd(vscode.workspace.workspaceFolders?.[0]);
    await this.runner.start(trimmed, cwd, opts);

    // Best-effort cleanup once the run ends — we keep the runner instance
    // alive briefly so subscribers don't race the close event.
    setTimeout(() => unsub(), 30_000);
  }

  private handleRunnerOutput(out: RunnerOutput): void {
    if (out.started) {
      this.post({ command: "runnerStarted", info: out.started });
      return;
    }
    if (out.event) {
      this.postEvent(out.event);
      return;
    }
    if (out.ended) {
      this.post({ command: "runnerEnded", info: out.ended });
      return;
    }
  }

  private postEvent(event: RunnerEvent): void {
    this.post({ command: "runnerEvent", runId: this.currentRunId, event });
  }

  private post(msg: ExtensionMessage): void {
    this.view?.webview.postMessage(msg);
  }

  private postError(message: string): void {
    this.post({ command: "runnerEvent", runId: this.currentRunId, event: { kind: "error", message } });
  }
}

function randomNonce(): string {
  const bytes = require("crypto").randomBytes(16);
  let s = "";
  for (const b of bytes) s += b.toString(16).padStart(2, "0");
  return s;
}

function newRunId(): string {
  return Math.random().toString(16).slice(2, 14).padEnd(12, "0");
}