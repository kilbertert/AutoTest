// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

// TrendpowerHealth probes three things:
//   1. uv is on PATH
//   2. trendpower Python package is importable
//   3. ~/.trendpower/mcp_servers.json parses and reports N servers
//
// All probes run as short-lived child processes with bounded timeouts so a
// missing/broken install never blocks the webview.

"use strict";

import { spawn } from "child_process";
import * as path from "path";
import * as os from "os";
import * as fs from "fs";
import { HealthUpdate } from "./protocol";

const PROBE_TIMEOUT_MS = 8000;

function runProcess(cmd: string, args: string[], timeoutMs: number): Promise<{ ok: boolean; stdout: string; stderr: string; code: number | null }> {
  return new Promise((resolve) => {
    let proc: ReturnType<typeof spawn>;
    try {
      proc = spawn(cmd, args, { shell: false, windowsHide: true });
    } catch (e) {
      resolve({ ok: false, stdout: "", stderr: String(e), code: -1 });
      return;
    }
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        try { proc.kill("SIGKILL"); } catch { /* ignore */ }
        resolve({ ok: false, stdout, stderr: stderr + "\n[timeout]", code: null });
      }
    }, timeoutMs);

    if (proc.stdout) proc.stdout.on("data", (b: Buffer) => { stdout += b.toString("utf-8"); });
    if (proc.stderr) proc.stderr.on("data", (b: Buffer) => { stderr += b.toString("utf-8"); });
    proc.on("error", (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        resolve({ ok: false, stdout, stderr: stderr + "\n" + String(err), code: -1 });
      }
    });
    proc.on("close", (code) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        resolve({ ok: code === 0, stdout, stderr, code });
      }
    });
  });
}

async function probeUv(): Promise<{ ok: boolean; version?: string; error?: string }> {
  const r = await runProcess("uv", ["--version"], PROBE_TIMEOUT_MS);
  if (!r.ok) {
    return { ok: false, error: r.stderr.trim() || `uv exited with code ${r.code}` };
  }
  // uv --version prints: "uv 0.4.7 (a80cc5f24 2024-09-24)"
  const m = r.stdout.match(/uv\s+([\d.]+)/);
  return { ok: true, version: m ? m[1] : r.stdout.trim().split("\n")[0] };
}

async function probeTrendpowerImport(): Promise<{ ok: boolean; version?: string; error?: string }> {
  // Probe against the workspace's trendpower-py install via `uv run --project`
  // so we hit the venv that has trendpower as an editable package. A bare
  // `uv run --no-project` from any cwd that contains a `trendpower/` *folder*
  // (e.g. the AutoGenesis repo root with its `trendpower/skills/` namespace)
  // will import the wrong thing and fail with "No module named
  // 'trendpower.community'".
  const candidates = [
    path.resolve(__dirname, "..", "..", "..", "..", "trendpower", "trendpower-py"),
    path.resolve(__dirname, "..", "..", "..", "trendpower", "trendpower-py"),
  ];
  for (const tp of candidates) {
    if (fs.existsSync(path.join(tp, "pyproject.toml"))) {
      const r = await runProcess("uv", ["run", "--project", tp, "python", "-c", "import trendpower, sys; print(getattr(trendpower, '__version__', 'unknown'))"], PROBE_TIMEOUT_MS);
      if (r.ok) {
        return { ok: true, version: r.stdout.trim().split("\n")[0] };
      }
    }
  }
  // Fallback: try the global python (in case trendpower is installed system-wide).
  const r = await runProcess("python", ["-c", "import trendpower, sys; print(getattr(trendpower, '__version__', 'unknown'))"], PROBE_TIMEOUT_MS);
  if (!r.ok) {
    return { ok: false, error: r.stderr.trim() || `import trendpower failed (code ${r.code})` };
  }
  return { ok: true, version: r.stdout.trim().split("\n")[0] };
}

async function probeMcpConfig(): Promise<{ servers: number; model: string | null; provider: string | null; errors: string[] }> {
  const configPath = path.join(os.homedir(), ".trendpower", "mcp_servers.json");
  const errors: string[] = [];
  if (!fs.existsSync(configPath)) {
    errors.push(`config not found: ${configPath}`);
    return { servers: 0, model: null, provider: null, errors };
  }
  let doc: any;
  try {
    doc = JSON.parse(fs.readFileSync(configPath, "utf-8"));
  } catch (e) {
    errors.push(`config parse failed: ${e instanceof Error ? e.message : String(e)}`);
    return { servers: 0, model: null, provider: null, errors };
  }
  // mcp_servers.json schema: { mcpServers: { <name>: {...} } }
  const servers = doc && typeof doc === "object" && doc.mcpServers && typeof doc.mcpServers === "object"
    ? Object.keys(doc.mcpServers).length
    : 0;

  // Provider/model come from env (set by the user outside this extension).
  const model = process.env.TRENDPOWER_MODEL || null;
  const provider = process.env.TRENDPOWER_PROVIDER || null;

  return { servers, model, provider, errors };
}

export async function probeHealth(): Promise<HealthUpdate> {
  const configPath = path.join(os.homedir(), ".trendpower", "mcp_servers.json");
  const errors: string[] = [];

  const [uvR, tpR, mcpR] = await Promise.all([
    probeUv(),
    probeTrendpowerImport(),
    probeMcpConfig(),
  ]);

  if (!uvR.ok) errors.push(`uv: ${uvR.error}`);
  if (!tpR.ok) errors.push(`trendpower: ${tpR.error}`);
  errors.push(...mcpR.errors);

  return {
    uv: uvR.ok,
    uvVersion: uvR.version,
    trendpower: tpR.ok,
    trendpowerVersion: tpR.version,
    mcpServers: mcpR.servers,
    model: mcpR.model,
    provider: mcpR.provider,
    configPath,
    errors,
  };
}