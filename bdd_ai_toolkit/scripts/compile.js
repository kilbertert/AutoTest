// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

// Build pipeline for trendpower-shell:
//   1. tsc → out/
//   2. copy resources/* → out/resources/
//   3. copy webview script (compiled .js) → out/resources/sidebar/sidebar.js

"use strict";

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "out");
const RESOURCES = path.join(ROOT, "resources");

function log(msg) {
  process.stdout.write(`[compile] ${msg}\n`);
}

function rmrf(p) {
  if (fs.existsSync(p)) {
    fs.rmSync(p, { recursive: true, force: true });
  }
}

function copyRecursive(srcDir, dstDir) {
  fs.mkdirSync(dstDir, { recursive: true });
  for (const entry of fs.readdirSync(srcDir, { withFileTypes: true })) {
    const s = path.join(srcDir, entry.name);
    const d = path.join(dstDir, entry.name);
    if (entry.isDirectory()) {
      copyRecursive(s, d);
    } else if (entry.isFile()) {
      fs.copyFileSync(s, d);
    }
  }
}

function main() {
  log("cleaning out/");
  rmrf(OUT);

  log("tsc -p ./");
  execSync("tsc -p ./", { cwd: ROOT, stdio: "inherit" });

  log("copying resources/ → out/resources/");
  copyRecursive(RESOURCES, path.join(OUT, "resources"));

  log("copying webview script → out/resources/sidebar/sidebar.js");
  const webviewScriptSrc = path.join(OUT, "src", "sidebar", "sidebarScript.js");
  const webviewScriptDst = path.join(OUT, "resources", "sidebar", "sidebar.js");
  if (fs.existsSync(webviewScriptSrc)) {
    fs.copyFileSync(webviewScriptSrc, webviewScriptDst);
  } else {
    process.stderr.write(`[compile] WARNING: ${webviewScriptSrc} not found; webview will not load\n`);
  }

  log("done.");
}

try {
  main();
} catch (err) {
  process.stderr.write(`[compile] FAILED: ${err && err.message ? err.message : err}\n`);
  process.exit(1);
}