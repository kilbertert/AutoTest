// trendpower-web frontend.
// One "turn" per user message, N "rounds" per turn (one per LLM call).
// Right inspector pane shows the active round's full prompt as readable text.

const elState = document.getElementById("state");
const elTurns = document.getElementById("turns");
const elEmpty = document.getElementById("empty");
const elCountTurn = document.getElementById("count-turn");
const elCountRound = document.getElementById("count-round");
const elInspectorTarget = document.getElementById("inspector-target");
const elInspectorBody = document.getElementById("inspector-body");
const elInspectorHint = document.getElementById("inspector-hint");
const elInspectorFollow = document.getElementById("inspector-follow");
const elInspectorCopy = document.getElementById("inspector-copy");

// ── State ─────────────────────────────────────────────────────────────────

const state = {
  turns: [],
  currentTurn: null,
  currentRound: null,
  globalRoundCount: 0,
  inspectorRoundN: null,   // globalN of round being inspected; null = follow latest
  follow: true,
};

const roundsByRequestId = new Map();
const roundsByGlobalN = new Map();

// ── Helpers ───────────────────────────────────────────────────────────────

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  }[c]));
}

function fmtJSON(value) {
  if (value === undefined) return "";
  if (value === null) return "null";
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function fmtDuration(ms) {
  if (ms == null || ms < 0) return "";
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  return `${(ms / 1000).toFixed(2)} 秒`;
}

function fmtBytes(n) {
  if (n < 1024) return `${n} 字符`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function partsToText(content) {
  if (content == null) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter((p) => p && (p.type === "text" || typeof p === "string"))
      .map((p) => (typeof p === "string" ? p : p.text || ""))
      .join("");
  }
  return "";
}

function messageKey(msg) {
  try { return JSON.stringify(msg); }
  catch { return String(msg); }
}

function romanize(n) {
  const map = [[10,"X"],[9,"IX"],[5,"V"],[4,"IV"],[1,"I"]];
  let r = "";
  for (const [v, s] of map) {
    while (n >= v) { r += s; n -= v; }
  }
  return r || "I";
}

function shorten(s, n) {
  if (!s) return "";
  s = String(s).replace(/\s+/g, " ");
  return s.length > n ? s.slice(0, n) + "…" : s;
}

// ── State transitions ─────────────────────────────────────────────────────

function startTurn(text, ts) {
  if (state.currentRound) finalizeRound(state.currentRound, ts);
  if (state.currentTurn) {
    state.currentTurn.endTs = ts;
    renderTurnMeta(state.currentTurn);
  }
  const turn = {
    n: state.turns.length + 1,
    userText: text || "",
    startTs: ts, endTs: null,
    rounds: [],
  };
  state.turns.push(turn);
  state.currentTurn = turn;
  state.currentRound = null;
  appendTurnDOM(turn);
  updateHeaderCounts();
}

function startRound(req, ts) {
  let turn = state.currentTurn;
  if (!turn) { startTurn("", ts); turn = state.currentTurn; }
  if (state.currentRound) finalizeRound(state.currentRound, ts);
  state.globalRoundCount += 1;
  const round = {
    n: turn.rounds.length + 1,
    globalN: state.globalRoundCount,
    request_id: req.request_id,
    provider: req.provider,
    mode: req.mode,
    payload: req.payload || {},
    startTs: ts, endTs: null,
    status: "streaming",
    output: { text: "", toolUses: [] },
    toolResults: [],
    usage: null,
  };
  turn.rounds.push(round);
  state.currentRound = round;
  if (round.request_id) roundsByRequestId.set(round.request_id, round);
  roundsByGlobalN.set(round.globalN, round);
  appendRoundDOM(round);
  renderTurnMeta(turn);
  updateHeaderCounts();
  if (state.follow) setInspectorRound(round.globalN, { follow: true });
}

function finalizeRound(round, ts) {
  if (round.status === "streaming") round.status = "done";
  if (!round.endTs) round.endTs = ts || Date.now() / 1000;
  renderRoundHeader(round);
  if (state.inspectorRoundN === round.globalN) renderInspector();
}

function applyStreamSnapshot(round, snapshot, ts) {
  if (!snapshot) return;
  if (Array.isArray(snapshot.content)) {
    round.output.text = "";
    round.output.toolUses = [];
    for (const part of snapshot.content) {
      if (!part) continue;
      if (part.type === "text") {
        round.output.text += part.text || "";
      } else if (part.type === "tool_use") {
        round.output.toolUses.push({
          id: part.id || part.tool_use_id,
          name: part.name,
          input: part.input,
        });
      }
    }
  }
  if (snapshot.tokenUsage) round.usage = snapshot.tokenUsage;
  if (ts) round.endTs = ts;
  renderRoundOutput(round);
  renderRoundHeader(round);
}

function applyAgentMessage(round, message) {
  if (!message) return;
  const role = message.role;
  if (role === "assistant") {
    applyStreamSnapshot(round, message, null);
    if (round.status === "streaming") {
      round.status = "done";
      renderRoundHeader(round);
    }
  } else if (role === "tool") {
    const parts = Array.isArray(message.content) ? message.content : [];
    for (const part of parts) {
      if (!part) continue;
      if (part.type === "tool_result") {
        round.toolResults.push({
          tool_use_id: part.tool_use_id,
          content: part.content,
          is_error: part.is_error,
        });
      }
    }
    renderToolBand(round);
  }
}

// ── Event dispatch ────────────────────────────────────────────────────────

function onEvent(evt) {
  const ts = evt.ts || Date.now() / 1000;
  hideEmptyState();
  if (evt.type === "user_input") {
    startTurn(evt.text || "", ts);
  } else if (evt.type === "llm_request") {
    startRound(evt, ts);
  } else if (evt.type === "llm_response_chunk") {
    const round = roundsByRequestId.get(evt.request_id) || state.currentRound;
    if (round) applyStreamSnapshot(round, evt.snapshot, ts);
  } else if (evt.type === "llm_response") {
    const round = roundsByRequestId.get(evt.request_id) || state.currentRound;
    if (round) {
      if (evt.usage) round.usage = evt.usage;
      finalizeRound(round, ts);
    }
  } else if (evt.type === "agent_event") {
    const inner = evt.event || {};
    if (inner.type === "message") {
      const round = state.currentRound;
      if (round) applyAgentMessage(round, inner.message);
    } else if (inner.type === "progress") {
      const round = state.currentRound;
      if (round) {
        round.progressHint = inner.subtype === "tool"
          ? `执行工具 ${inner.name || ""}`
          : "推理中";
        renderRoundHeader(round);
      }
    }
  } else if (evt.type === "trace") {
    traceOnEvent(evt);
  } else if (evt.type === "error") {
    if (state.currentRound) {
      state.currentRound.status = "error";
      state.currentRound.errorMessage = evt.message;
      renderRoundHeader(state.currentRound);
    }
  }
}

// ── Rendering: utils ──────────────────────────────────────────────────────

function hideEmptyState() {
  if (elEmpty && !elEmpty.classList.contains("hidden")) {
    elEmpty.classList.add("hidden");
  }
}

function updateHeaderCounts() {
  elCountTurn.textContent = String(state.turns.length);
  elCountRound.textContent = String(state.globalRoundCount);
}

// ── Rendering: turn ───────────────────────────────────────────────────────

function appendTurnDOM(turn) {
  const wrap = document.createElement("section");
  wrap.className = "turn";
  wrap.id = `turn-${turn.n}`;
  wrap.innerHTML = `
    <header class="turn-header">
      <div class="turn-label">第 ${turn.n} 问 · Turn № ${turn.n}</div>
      <div class="turn-meta" id="turn-meta-${turn.n}"></div>
    </header>
    <blockquote class="turn-user">${escapeHtml(turn.userText || "(空提问)")}</blockquote>
    <div class="rounds" id="rounds-${turn.n}"></div>
  `;
  elTurns.appendChild(wrap);
  renderTurnMeta(turn);
}

function renderTurnMeta(turn) {
  const el = document.getElementById(`turn-meta-${turn.n}`);
  if (!el) return;
  const tools = turn.rounds.reduce((acc, r) => acc + r.toolResults.length, 0);
  const elapsed = turn.endTs && turn.startTs ? (turn.endTs - turn.startTs) * 1000 : null;
  const elapsedTxt = elapsed != null ? ` · ${fmtDuration(elapsed)}` : "";
  el.textContent = `${turn.rounds.length} 轮调用 · ${tools} 次工具执行${elapsedTxt}`;
}

// ── Rendering: round ──────────────────────────────────────────────────────

function appendRoundDOM(round) {
  const host = document.getElementById(`rounds-${state.currentTurn.n}`);
  if (!host) return;

  const prevRound = state.currentTurn.rounds[state.currentTurn.rounds.length - 2];
  if (prevRound && !document.getElementById(`band-${prevRound.globalN}`)) {
    const band = document.createElement("div");
    band.className = "tool-band";
    band.id = `band-${prevRound.globalN}`;
    band.innerHTML = `
      <div class="band-head">工具执行 · Tool Execution</div>
      <div class="band-body" id="band-body-${prevRound.globalN}">
        <div class="muted">（等待工具结果…）</div>
      </div>
      <div class="band-foot">这一段结果会作为 <strong>★ 新增输入</strong> 进入下面的 <strong>第 ${prevRound.n + 1} 轮 (Round ${romanize(prevRound.n + 1)})</strong></div>
    `;
    host.appendChild(band);
    renderToolBand(prevRound);
  }

  const card = document.createElement("article");
  card.className = "round";
  card.id = `round-${round.globalN}`;
  card.dataset.globalN = String(round.globalN);
  card.innerHTML = `
    <div class="round-stamp">Round ${romanize(round.n)}<span class="round-overall">№ ${round.globalN}</span></div>
    <header class="round-header" id="round-head-${round.globalN}"></header>

    <section class="stage stage-input">
      <h3 class="stage-label">
        输入
        <span class="stage-sub">模型这一轮看见的全部内容</span>
      </h3>
      <div class="layers" id="layers-${round.globalN}"></div>
    </section>

    <div class="flow">
      <span class="flow-arrow"><span class="arrow-glyph">↓</span>送入模型 · 模型推理 · 返回<span class="arrow-glyph">↓</span></span>
    </div>

    <section class="stage stage-output">
      <h3 class="stage-label">
        输出
        <span class="stage-sub">模型这一轮原样返回的内容</span>
      </h3>
      <div class="output-text" id="out-text-${round.globalN}"></div>
      <div class="output-tools" id="out-tools-${round.globalN}"></div>
    </section>
  `;
  card.addEventListener("click", (e) => {
    // Don't hijack clicks on interactive children (toggles, links).
    if (e.target.closest("[data-toggle], button, a, .layer-toggle, .msg-head")) return;
    setInspectorRound(round.globalN, { follow: false });
  });
  host.appendChild(card);

  renderRoundHeader(round);
  renderRoundInput(round);
  renderRoundOutput(round);
  requestAnimationFrame(() => card.classList.add("visible"));
}

function renderRoundHeader(round) {
  const el = document.getElementById(`round-head-${round.globalN}`);
  if (!el) return;
  const p = round.payload || {};
  const model = p.model || "?";
  const duration = round.endTs && round.startTs
    ? fmtDuration((round.endTs - round.startTs) * 1000)
    : "";
  let tokens = "";
  if (round.usage) {
    tokens = `${round.usage.promptTokens ?? 0} → ${round.usage.completionTokens ?? 0} tok`;
  }
  const statusClass = round.status;
  const statusLabels = { streaming: "推理中", done: "完成", error: "错误" };
  let statusText = statusLabels[round.status] || round.status;
  if (round.status === "streaming" && round.progressHint) statusText = round.progressHint;
  el.innerHTML = `
    <div class="round-meta">
      <span class="model">${escapeHtml(model)}</span>
      <span class="provider">${escapeHtml(round.provider)}</span>
      <span class="status status-${statusClass}">${escapeHtml(statusText)}</span>
      ${duration ? `<span class="duration">${escapeHtml(duration)}</span>` : ""}
      ${tokens ? `<span class="tokens">${escapeHtml(tokens)}</span>` : ""}
    </div>
  `;
}

// ── Input: 4 layers ───────────────────────────────────────────────────────

function renderRoundInput(round) {
  const host = document.getElementById(`layers-${round.globalN}`);
  if (!host) return;
  const p = round.payload || {};

  const systemText = (() => {
    if (typeof p.system === "string") return p.system;
    if (Array.isArray(p.system)) return partsToText(p.system) || fmtJSON(p.system);
    if (p.system) return fmtJSON(p.system);
    if (Array.isArray(p.messages)) {
      const sys = p.messages.find((m) => m && m.role === "system");
      if (sys) return partsToText(sys.content) || fmtJSON(sys.content);
    }
    return "";
  })();

  const messages = Array.isArray(p.messages)
    ? p.messages.filter((m) => !m || m.role !== "system")
    : [];

  const prevRound = previousRoundInTurn(round);
  const prevKeys = new Set();
  if (prevRound) {
    const prevMsgs = Array.isArray(prevRound.payload.messages)
      ? prevRound.payload.messages.filter((m) => !m || m.role !== "system")
      : [];
    for (const m of prevMsgs) prevKeys.add(messageKey(m));
  }

  const tools = Array.isArray(p.tools) ? p.tools : [];

  const rest = { ...p };
  delete rest.messages;
  delete rest.system;
  delete rest.tools;
  delete rest.stream;
  delete rest.stream_options;

  host.innerHTML = "";

  // Layer 1: system prompt
  host.appendChild(layerCard({
    n: 1,
    title: "系统提示",
    titleEn: "system prompt",
    meta: systemText ? fmtBytes(systemText.length) : "(空)",
    collapsible: true,
    bodyHTML: systemText
      ? `<pre>${escapeHtml(systemText)}</pre>`
      : `<div class="muted">（本轮没有 system 内容）</div>`,
  }));

  // Layer 2: messages
  const newCount = prevRound ? messages.filter((m) => !prevKeys.has(messageKey(m))).length : 0;
  const newBadge = newCount > 0
    ? `<span class="meta-chip" style="background:rgba(245,205,58,0.18); color:var(--ink); border-color:var(--highlight);">★ 本轮新增 ${newCount}</span>`
    : "";
  const messagesLayer = layerCard({
    n: 2,
    title: "消息历史",
    titleEn: "messages",
    meta: `${messages.length} 条${newBadge ? "" : ""}`,
    metaExtra: newBadge,
    collapsible: false,
    bodyHTML: `<div class="messages" id="msglist-${round.globalN}"></div>`,
  });
  host.appendChild(messagesLayer);
  const msgList = messagesLayer.querySelector(`#msglist-${round.globalN}`);
  messages.forEach((msg) => {
    const isNew = prevRound && !prevKeys.has(messageKey(msg));
    msgList.appendChild(renderMessageRow(msg, isNew));
  });

  // Layer 3: tools
  const toolPreview = tools.length
    ? tools.slice(0, 4).map((t) => {
        const name = t.function?.name || t.name || "?";
        return name;
      }).join("、") + (tools.length > 4 ? `、… 共 ${tools.length} 个` : "")
    : "(空)";
  host.appendChild(layerCard({
    n: 3,
    title: "工具集",
    titleEn: "tools",
    meta: tools.length ? `${tools.length} 个工具` : "(空)",
    collapsible: true,
    bodyHTML: tools.length
      ? `<div class="layer-preview muted" style="margin-bottom:8px; font-size:12px;">前几个：${escapeHtml(toolPreview)}</div><pre>${escapeHtml(fmtJSON(tools))}</pre>`
      : `<div class="muted">（本轮未声明任何工具）</div>`,
  }));

  // Layer 4: params
  const paramsHTML = Object.entries(rest).length
    ? `<div class="params">${Object.entries(rest).map(([k, v]) => {
        const vText = typeof v === "object" ? fmtJSON(v) : String(v);
        return `<span class="param-row"><span class="param-k">${escapeHtml(k)}</span><span class="param-v">${escapeHtml(vText)}</span></span>`;
      }).join("")}</div>`
    : `<div class="muted">（无）</div>`;
  host.appendChild(layerCard({
    n: 4,
    title: "调用参数",
    titleEn: "params",
    meta: `${Object.keys(rest).length} 项`,
    collapsible: false,
    bodyHTML: paramsHTML,
  }));
}

function layerCard({ n, title, titleEn, meta, metaExtra, collapsible, bodyHTML }) {
  const wrap = document.createElement("div");
  wrap.className = `layer layer-${n}`;
  const toggle = collapsible ? `<span class="layer-toggle">▸</span>` : "";
  const markerCls = collapsible ? "layer-marker clickable" : "layer-marker";
  wrap.innerHTML = `
    <div class="${markerCls}"${collapsible ? ' data-toggle' : ''}>
      <span class="layer-num">第 ${n} 层</span>
      <span class="layer-title">${escapeHtml(title)}<span class="layer-title-en">${escapeHtml(titleEn)}</span></span>
      <span class="layer-meta"><span class="meta-chip">${escapeHtml(meta)}</span>${metaExtra || ""}</span>
      ${toggle}
    </div>
    <div class="layer-body${collapsible ? " collapsed" : ""}">${bodyHTML}</div>
  `;
  if (collapsible) {
    const marker = wrap.querySelector(".layer-marker");
    marker.addEventListener("click", () => {
      const body = wrap.querySelector(".layer-body");
      body.classList.toggle("collapsed");
      const t = wrap.querySelector(".layer-toggle");
      if (t) t.classList.toggle("open");
    });
  }
  return wrap;
}

function renderMessageRow(msg, isNew) {
  const row = document.createElement("div");
  const role = msg && msg.role ? msg.role : "?";
  row.className = `msg msg-${role}${isNew ? " is-new" : ""}`;
  const preview = previewForMessage(msg);
  const newTag = isNew ? `<span class="new-tag">本轮新增</span>` : "";
  row.innerHTML = `
    <div class="msg-head clickable" data-toggle>
      <span class="msg-role">${escapeHtml(role)}</span>
      <span class="msg-preview">${escapeHtml(preview)}</span>
      ${newTag}
      <span class="toggle-arrow">▸</span>
    </div>
    <div class="msg-body collapsed"><pre>${escapeHtml(fmtJSON(msg))}</pre></div>
  `;
  const head = row.querySelector(".msg-head");
  head.addEventListener("click", (e) => {
    e.stopPropagation();
    const body = row.querySelector(".msg-body");
    body.classList.toggle("collapsed");
    const arrow = head.querySelector(".toggle-arrow");
    if (arrow) arrow.classList.toggle("open");
  });
  return row;
}

function previewForMessage(msg) {
  if (!msg) return "";
  const content = msg.content;
  if (typeof content === "string") return shorten(content, 140);
  if (Array.isArray(content)) {
    const parts = [];
    for (const p of content) {
      if (!p) continue;
      if (p.type === "text") parts.push(p.text || "");
      else if (p.type === "tool_use") parts.push(`🔧 ${p.name}(…)`);
      else if (p.type === "tool_result") {
        const c = typeof p.content === "string" ? p.content : partsToText(p.content);
        parts.push(`◀ ${shorten(c, 100)}`);
      } else if (p.type === "thinking") parts.push("💭 (思考中)");
    }
    return shorten(parts.join("  "), 200);
  }
  return shorten(fmtJSON(content), 140);
}

function previousRoundInTurn(round) {
  const turn = state.currentTurn || state.turns[state.turns.length - 1];
  if (!turn) return null;
  const idx = turn.rounds.indexOf(round);
  if (idx <= 0) return null;
  return turn.rounds[idx - 1];
}

// ── Output ────────────────────────────────────────────────────────────────

function renderRoundOutput(round) {
  const textEl = document.getElementById(`out-text-${round.globalN}`);
  if (textEl) {
    if (round.output.text) {
      textEl.innerHTML = `<div class="assistant-text">${escapeHtml(round.output.text)}</div>`;
    } else if (round.status === "streaming") {
      textEl.innerHTML = `<div class="assistant-placeholder">… 等待模型输出</div>`;
    } else {
      textEl.innerHTML = `<div class="assistant-placeholder">（无文本输出，仅有工具调用）</div>`;
    }
  }
  const toolsEl = document.getElementById(`out-tools-${round.globalN}`);
  if (toolsEl) {
    toolsEl.innerHTML = "";
    for (const t of round.output.toolUses) {
      const card = document.createElement("div");
      card.className = "tool-use-card";
      card.innerHTML = `
        <div class="tool-use-head">🔧 <strong>${escapeHtml(t.name)}</strong></div>
        <pre>${escapeHtml(fmtJSON(t.input))}</pre>
      `;
      toolsEl.appendChild(card);
    }
    if (!round.output.toolUses.length && round.status === "done") {
      const note = document.createElement("div");
      note.className = "end-note";
      note.textContent = "模型没有再调用工具——这一轮就是最终回答。";
      toolsEl.appendChild(note);
    }
  }
  if (state.inspectorRoundN === round.globalN) renderInspector();
}

function renderToolBand(round) {
  const body = document.getElementById(`band-body-${round.globalN}`);
  if (!body) return;
  if (!round.toolResults.length) {
    body.innerHTML = `<div class="muted">（等待工具结果…）</div>`;
    return;
  }
  body.innerHTML = "";
  for (const tr of round.toolResults) {
    const text = typeof tr.content === "string" ? tr.content : partsToText(tr.content) || fmtJSON(tr.content);
    const card = document.createElement("div");
    card.className = `tool-result${tr.is_error ? " is-error" : ""}`;
    card.innerHTML = `
      <div class="tool-result-head">tool_result <span class="muted">${escapeHtml(tr.tool_use_id || "")}</span></div>
      <pre>${escapeHtml(shorten(text, 4000))}</pre>
    `;
    body.appendChild(card);
  }
}

// ── Inspector pane ────────────────────────────────────────────────────────

function setInspectorRound(globalN, { follow = false } = {}) {
  state.inspectorRoundN = globalN;
  state.follow = !!follow;
  document.querySelectorAll(".round.inspecting").forEach((el) => el.classList.remove("inspecting"));
  if (globalN != null) {
    const card = document.getElementById(`round-${globalN}`);
    if (card) card.classList.add("inspecting");
  }
  if (elInspectorFollow) elInspectorFollow.classList.toggle("active", state.follow);
  renderInspector();
}

function renderInspector() {
  const n = state.inspectorRoundN;
  if (n == null || !roundsByGlobalN.has(n)) {
    elInspectorTarget.textContent = "尚无数据";
    if (elInspectorHint) elInspectorHint.style.display = "";
    elInspectorBody.innerHTML = `<div class="inspector-empty">在终端 TUI 里随便问一句，<em>第一轮的完整输入</em>就会出现在这里。</div>`;
    return;
  }
  const round = roundsByGlobalN.get(n);
  if (elInspectorHint) elInspectorHint.style.display = "none";

  const turnN = state.turns.find((t) => t.rounds.includes(round))?.n;
  elInspectorTarget.textContent =
    `第 ${turnN} 问 / Round ${romanize(round.n)} (#${round.globalN})  ·  ${round.provider}  ·  ${round.payload?.model || "?"}`;

  const lines = [];
  const p = round.payload || {};

  // Previous-round comparison for ★new diff highlights inside inspector too.
  const prev = previousRoundInTurn(round);
  const prevKeys = new Set();
  if (prev) {
    const prevMsgs = Array.isArray(prev.payload.messages)
      ? prev.payload.messages.filter((m) => !m || m.role !== "system")
      : [];
    for (const m of prevMsgs) prevKeys.add(messageKey(m));
  }

  // Header banner
  lines.push(`<span class="ins-sep">═══════════ 完整输入 · 第 ${turnN} 问 / Round ${romanize(round.n)} ═══════════</span>`);
  lines.push(`<span class="ins-meta">model    = ${escapeHtml(p.model || "?")}</span>`);
  lines.push(`<span class="ins-meta">provider = ${escapeHtml(round.provider)}</span>`);
  lines.push(`<span class="ins-meta">mode     = ${escapeHtml(round.mode || "?")}</span>`);
  lines.push("");

  // SYSTEM
  const sysText = (() => {
    if (typeof p.system === "string") return p.system;
    if (Array.isArray(p.system)) return partsToText(p.system) || fmtJSON(p.system);
    if (p.system) return fmtJSON(p.system);
    if (Array.isArray(p.messages)) {
      const sys = p.messages.find((m) => m && m.role === "system");
      if (sys) return partsToText(sys.content) || fmtJSON(sys.content);
    }
    return "";
  })();
  lines.push(`<span class="ins-sep">────────── ▼ 第 1 层 · 系统提示 (system) ──────────</span>`);
  if (sysText) {
    lines.push(`<span class="ins-content">${escapeHtml(sysText)}</span>`);
  } else {
    lines.push(`<span class="ins-meta">（本轮无 system 内容）</span>`);
  }
  lines.push("");

  // MESSAGES
  const messages = Array.isArray(p.messages)
    ? p.messages.filter((m) => !m || m.role !== "system")
    : [];
  lines.push(`<span class="ins-sep">────────── ▼ 第 2 层 · 消息历史 (messages, ${messages.length} 条) ──────────</span>`);
  messages.forEach((msg, i) => {
    const role = msg?.role || "?";
    const isNew = prev && !prevKeys.has(messageKey(msg));
    const star = isNew ? `<span class="ins-new">★ 本轮新增</span> ` : "";
    lines.push("");
    lines.push(`<span class="ins-role">[${i + 1}] ${role.toUpperCase()}</span>  ${star}`);
    const content = msg?.content;
    if (typeof content === "string") {
      const body = `<span class="ins-content">${escapeHtml(content)}</span>`;
      lines.push(isNew ? `<span class="ins-new">${body}</span>` : body);
    } else if (Array.isArray(content)) {
      for (const part of content) {
        if (!part) continue;
        if (part.type === "text") {
          const t = part.text || "";
          if (t) {
            const body = `<span class="ins-content">${escapeHtml(t)}</span>`;
            lines.push(isNew ? `<span class="ins-new">${body}</span>` : body);
          }
        } else if (part.type === "tool_use") {
          const body = `<span class="ins-content">→ tool_use: <b>${escapeHtml(part.name)}</b>${escapeHtml(`(${fmtJSON(part.input)})`)}</span>`;
          lines.push(isNew ? `<span class="ins-new">${body}</span>` : body);
        } else if (part.type === "tool_result") {
          const c = typeof part.content === "string" ? part.content : partsToText(part.content) || fmtJSON(part.content);
          const head = `↩ tool_result${part.tool_use_id ? ` (id=${escapeHtml(part.tool_use_id)})` : ""}:`;
          const body = `<span class="ins-content">${head}\n${escapeHtml(c)}</span>`;
          lines.push(isNew ? `<span class="ins-new">${body}</span>` : body);
        } else if (part.type === "thinking") {
          lines.push(`<span class="ins-meta">💭 (thinking block, ${(part.thinking || "").length} 字符)</span>`);
        } else {
          lines.push(`<span class="ins-meta">[${part.type}] ${escapeHtml(fmtJSON(part))}</span>`);
        }
      }
    } else if (content != null) {
      lines.push(`<span class="ins-content">${escapeHtml(fmtJSON(content))}</span>`);
    }
  });
  lines.push("");

  // TOOLS
  const tools = Array.isArray(p.tools) ? p.tools : [];
  lines.push(`<span class="ins-sep">────────── ▼ 第 3 层 · 工具集 (tools, ${tools.length} 个) ──────────</span>`);
  if (tools.length) {
    tools.forEach((t, i) => {
      const name = t.function?.name || t.name || "?";
      const desc = t.function?.description || t.description || "";
      lines.push(`<span class="ins-role">• ${escapeHtml(name)}</span>${desc ? `<span class="ins-meta"> — ${escapeHtml(shorten(desc, 80))}</span>` : ""}`);
    });
  } else {
    lines.push(`<span class="ins-meta">（无）</span>`);
  }
  lines.push("");

  // PARAMS
  const rest = { ...p };
  delete rest.messages; delete rest.system; delete rest.tools;
  delete rest.stream; delete rest.stream_options;
  lines.push(`<span class="ins-sep">────────── ▼ 第 4 层 · 调用参数 (params) ──────────</span>`);
  for (const [k, v] of Object.entries(rest)) {
    const vText = typeof v === "object" ? fmtJSON(v) : String(v);
    lines.push(`<span class="ins-meta">${escapeHtml(k)} = ${escapeHtml(vText)}</span>`);
  }
  lines.push("");
  lines.push(`<span class="ins-sep">═══════════ 本轮输入结束 · 上述全部内容会送进 LLM ═══════════</span>`);

  elInspectorBody.innerHTML = lines.join("\n");
}

// Inspector buttons
elInspectorFollow.addEventListener("click", () => {
  state.follow = true;
  if (state.globalRoundCount > 0) {
    setInspectorRound(state.globalRoundCount, { follow: true });
  } else {
    setInspectorRound(null, { follow: true });
  }
});
elInspectorCopy.addEventListener("click", async () => {
  // Strip HTML tags from inspector body for plain-text copy.
  const text = elInspectorBody.textContent || "";
  try {
    await navigator.clipboard.writeText(text);
    elInspectorCopy.textContent = "✓ 已复制";
    setTimeout(() => { elInspectorCopy.textContent = "⧉ 复制"; }, 1500);
  } catch {
    elInspectorCopy.textContent = "✗ 复制失败";
    setTimeout(() => { elInspectorCopy.textContent = "⧉ 复制"; }, 1500);
  }
});

// ── SSE ───────────────────────────────────────────────────────────────────

function setStatus(text, cls) {
  elState.textContent = text;
  elState.className = `state ${cls}`;
}

function connect() {
  const es = new EventSource("/events");
  es.addEventListener("open", () => setStatus("● 在线", "live"));
  es.addEventListener("error", () => setStatus("○ 重连中", "broken"));
  es.addEventListener("message", (raw) => {
    let event;
    try { event = JSON.parse(raw.data); } catch { return; }
    onEvent(event);
  });
}

// ===========================================================================
// Live execution trace (run → step → llm/tool) — fed by `type: "trace"` events
// emitted by trendpower.agent.tracing's middleware via the BroadcasterSink.
// ===========================================================================

const traceState = {
  spans: new Map(), // id -> { kind, id, parent, attrs, end, closed, el, childrenEl, order }
  order: 0,
  runs: 0,
};
const elTraceBody = document.getElementById("trace-body");
const elTraceSub = document.getElementById("trace-sub");
const elTracePanel = document.getElementById("trace-panel");

function traceFmtDur(ms) {
  if (ms == null) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

function traceLabel(sp) {
  const a = sp.attrs || {};
  const e = sp.end || {};
  const dur = traceFmtDur(e.duration_ms);
  if (sp.kind === "run") {
    const tag = a.subagent ? "sub-agent" : "run";
    const status = sp.closed
      ? `<span class="tr-ok">✓ ${escapeHtml(e.outcome || "done")}</span>`
      : `<span class="tr-run">● running</span>`;
    return `<span class="tr-kind tr-${a.subagent ? "sub" : "runk"}">${tag}</span>` +
      `<span class="tr-id">${escapeHtml(sp.id)}</span>` +
      `<span class="tr-meta">${escapeHtml(a.model || "?")} · ${a.tools ?? "?"} tools</span>${status}`;
  }
  if (sp.kind === "step") {
    return `<span class="tr-kind tr-step">step ${a.step ?? "?"}</span><span class="tr-dur">${dur}</span>`;
  }
  if (sp.kind === "llm") {
    const toks = e.prompt_tokens != null
      ? `<span class="tr-tok">↑${e.prompt_tokens} ↓${e.completion_tokens ?? "?"}</span>` : "";
    const run = sp.closed ? "" : `<span class="tr-run">●</span>`;
    return `<span class="tr-kind tr-llm">llm</span><span class="tr-dur">${dur}</span>${toks}${run}`;
  }
  if (sp.kind === "tool") {
    const mark = !sp.closed
      ? `<span class="tr-run">●</span>`
      : (e.ok ? `<span class="tr-ok">✓</span>` : `<span class="tr-err">✗</span>`);
    const inp = a.input ? `<span class="tr-inp">${escapeHtml(String(a.input).slice(0, 120))}</span>` : "";
    return `${mark}<span class="tr-kind tr-tool">${escapeHtml(a.name || "?")}</span><span class="tr-dur">${dur}</span>${inp}`;
  }
  if (sp.kind === "compaction") {
    return `<span class="tr-kind tr-comp">⟳ compaction</span>` +
      `<span class="tr-meta">${a.messages_before}→${a.messages_after} msgs (~${a.estimated_tokens} tok)</span>`;
  }
  return `<span class="tr-kind">${escapeHtml(sp.kind)}</span>`;
}

function traceRender(sp) {
  if (sp.el) sp.el.querySelector(".tr-line").innerHTML = traceLabel(sp);
}

function traceMakeNode(sp) {
  const node = document.createElement("div");
  node.className = `tr-node tr-node-${sp.kind}`;
  const line = document.createElement("div");
  line.className = "tr-line";
  line.innerHTML = traceLabel(sp);
  node.appendChild(line);
  const children = document.createElement("div");
  children.className = "tr-children";
  node.appendChild(children);
  sp.el = node;
  sp.childrenEl = children;
  return node;
}

function traceOnEvent(evt) {
  if (elTracePanel) elTracePanel.classList.remove("collapsed");
  if (evt.kind === "begin_run") {
    if (evt.is_top) traceState.runs += 1;
    if (elTraceSub) elTraceSub.textContent = `运行 #${traceState.runs}`;
    return;
  }
  const ev = evt.event;
  if (!ev || !ev.id) return;

  let sp = traceState.spans.get(ev.id);
  if (!sp) {
    sp = {
      kind: ev.span || "?", id: ev.id, parent: ev.parent || null,
      attrs: {}, end: null, closed: false, order: traceState.order++,
    };
    traceState.spans.set(ev.id, sp);
  }

  if (ev.t === "start" || ev.t === "event") {
    // Copy span attributes (everything except the envelope fields).
    for (const k of Object.keys(ev)) {
      if (!["t", "span", "id", "parent", "ts"].includes(k)) sp.attrs[k] = ev[k];
    }
    if (!sp.el) {
      const node = traceMakeNode(sp);
      const parent = sp.parent && traceState.spans.get(sp.parent);
      const container = parent && parent.childrenEl ? parent.childrenEl : elTraceBody;
      container.appendChild(node);
      // Keep the newest activity in view.
      if (elTraceBody) elTraceBody.scrollTop = elTraceBody.scrollHeight;
    }
    if (ev.t === "event") { sp.closed = true; sp.end = sp.attrs; }
  } else if (ev.t === "end") {
    sp.end = ev;
    sp.closed = true;
  }
  traceRender(sp);
}

if (elTracePanel) {
  const head = document.getElementById("trace-toggle");
  if (head) head.addEventListener("click", () => elTracePanel.classList.toggle("collapsed"));
}

// Initial render
setInspectorRound(null, { follow: true });
connect();
