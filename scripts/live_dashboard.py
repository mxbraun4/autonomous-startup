"""Live dashboard for autonomous run observability events."""

from __future__ import annotations

import argparse

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse
import webbrowser

if __package__:
    from ._bootstrap import add_repo_root_to_path
else:
    from _bootstrap import add_repo_root_to_path

REPO_ROOT = add_repo_root_to_path(__file__)

from src.framework.observability.dashboard import build_snapshot_from_ndjson


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Startup-VC Platform — Build Dashboard</title>
  <style>
    :root {
      --ink: #1a1a1a;
      --ink-soft: #6b7280;
      --surface: #ffffff;
      --surface-strong: #ffffff;
      --bg: #f7f7f8;
      --line: #e5e5e5;
      --accent: #0088FE;
      --accent-light: #e8f4ff;
      --danger: #dc2626;
      --ok: #16a34a;
      --warn: #d97706;
      --radius: 12px;
      --shadow: 0 1px 3px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      min-height: 100vh;
    }
    .frame {
      width: min(1320px, 96vw);
      margin: 18px auto 28px;
      display: grid;
      gap: 12px;
    }
    .hero {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 16px 20px;
      box-shadow: var(--shadow);
      animation: rise 480ms ease-out both;
    }
    .hero h1 { margin: 0; font-size: clamp(20px, 2.7vw, 28px); font-weight: 600; letter-spacing: -0.01em; color: var(--ink); }
    .hero h1 span { color: var(--ink); }
    .hero p { margin: 6px 0 0; color: var(--ink-soft); font-size: 13px; }
    .controls {
      display: grid;
      grid-template-columns: 1.5fr auto auto auto;
      gap: 10px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 12px;
      box-shadow: var(--shadow);
      animation: rise 580ms ease-out both;
    }
    .controls label { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--ink-soft); margin-bottom: 4px; }
    select, button, input[type="number"] {
      width: 100%;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--ink);
      font-size: 13px;
      font-weight: 500;
      transition: border-color 150ms;
    }
    select:focus, input[type="number"]:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-light); }
    button {
      cursor: pointer;
      background: var(--accent);
      color: #ffffff;
      border-color: var(--accent);
      font-weight: 600;
      transition: opacity 150ms;
    }
    button:hover { opacity: 0.85; }
    .auto-wrap {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 14px 16px;
      box-shadow: var(--shadow);
      animation: rise 520ms ease-out both;
    }
    .card:nth-child(2) { animation-delay: 60ms; }
    .card:nth-child(3) { animation-delay: 120ms; }
    .card:nth-child(4) { animation-delay: 180ms; }
    .card:nth-child(5) { animation-delay: 240ms; }
    .label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--ink-soft);
      margin-bottom: 6px;
      font-weight: 500;
    }
    .value {
      font-size: clamp(19px, 2.4vw, 28px);
      font-weight: 700;
      line-height: 1.1;
      color: var(--ink);
    }
    .meta { font-size: 12px; color: var(--ink-soft); margin-top: 6px; }
    .grid {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 10px;
    }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
      animation: rise 620ms ease-out both;
    }
    .panel h2 {
      margin: 0;
      padding: 10px 14px;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--ink-soft);
      border-bottom: 1px solid var(--line);
      background: #fafafa;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th {
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 8px 12px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--ink-soft);
      background: #fafafa;
    }
    td {
      text-align: left;
      border-bottom: 1px solid #f0f0f0;
      padding: 8px 12px;
      vertical-align: top;
      word-break: break-word;
      color: var(--ink);
    }
    tbody tr {
      animation: rowIn 220ms ease-out both;
      transition: background 120ms;
    }
    tbody tr:hover { background: #f9fafb; }
    .status {
      display: inline-block;
      border-radius: 999px;
      padding: 3px 9px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    .status.running { color: #0369a1; background: var(--accent-light); }
    .status.completed { color: #15803d; background: #f0fdf4; }
    .status.stopped { color: #b91c1c; background: #fef2f2; }
    .status.paused { color: #b45309; background: #fffbeb; }
    .status.warn { color: #b45309; background: #fffbeb; }
    .status.fail { color: #b91c1c; background: #fef2f2; }
    .status.pass { color: #15803d; background: #f0fdf4; }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 10px 14px;
    }
    .chip {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 500;
      background: #fafafa;
      color: var(--ink);
      white-space: nowrap;
    }
    .expandable {
      cursor: pointer;
      position: relative;
    }
    .expandable::after {
      content: " [+]";
      color: var(--accent);
      font-size: 10px;
      font-weight: 600;
    }
    .expandable.expanded::after {
      content: " [-]";
    }
    .expandable .full-text {
      display: none;
      margin-top: 6px;
      padding: 8px 10px;
      background: #f7f7f8;
      border: 1px solid var(--line);
      border-radius: 6px;
      font-size: 12px;
      line-height: 1.5;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 400px;
      overflow-y: auto;
    }
    .expandable.expanded .full-text {
      display: block;
    }
    #agentReasoningBody td:nth-child(4),
    #agentReasoningBody td:nth-child(5) {
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      line-height: 1.5;
      max-width: 600px;
    }
    #sharedKnowledgeBody td:nth-child(5),
    #learningsBody td:nth-child(3) {
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 12px;
      line-height: 1.5;
      max-width: 600px;
    }

    /* ── Tree View ── */
    .tree-container { padding: 16px 20px; }
    .tree-root {
      margin-bottom: 14px;
      padding-bottom: 10px;
      border-bottom: 1px dashed var(--line);
    }
    .tree-root:last-child { border-bottom: none; }
    .tree-node {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      padding: 4px 0;
    }
    .tree-branch {
      display: flex;
      flex-direction: column;
      margin-left: 20px;
      padding-left: 14px;
      border-left: 2px solid var(--line);
    }
    .tree-branch .tree-node { position: relative; }
    .tree-branch .tree-node::before {
      content: "";
      position: absolute;
      left: -14px;
      top: 13px;
      width: 12px;
      height: 2px;
      background: var(--line);
    }
    .tree-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      margin-top: 4px;
      flex-shrink: 0;
    }
    .tree-dot.coordinator { background: var(--accent); }
    .tree-dot.agent { background: var(--ok); }
    .tree-dot.failed { background: var(--danger); }
    .tree-label {
      font-size: 12px;
      font-weight: 600;
      color: var(--ink);
    }
    .tree-detail {
      font-size: 11px;
      color: var(--ink-soft);
      line-height: 1.4;
      margin-top: 2px;
      word-break: break-word;
    }
    .tree-empty {
      color: var(--ink-soft);
      font-size: 13px;
      padding: 12px 0;
    }
    .error {
      margin: 0;
      padding: 8px 12px;
      color: #b91c1c;
      font-size: 12px;
      border-top: 1px solid #fecaca;
      background: #fef2f2;
      display: none;
    }
    @keyframes rise {
      from { transform: translateY(4px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }
    @keyframes rowIn {
      from { opacity: 0; transform: translateX(3px); }
      to { opacity: 1; transform: translateX(0); }
    }
    @media (max-width: 1080px) {
      .cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 720px) {
      .controls { grid-template-columns: 1fr; }
      .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .frame { width: min(100vw, 96vw); }
    }
  </style>
</head>
<body>
  <main class="frame">
    <section class="hero">
      <h1>Startup-VC Platform <span>— Build Dashboard</span></h1>
      <p id="heroMeta">Waiting for events...</p>
    </section>

    <section class="controls">
      <div>
        <label for="runSelect">Run</label>
        <select id="runSelect">
          <option value="">Latest run (auto)</option>
        </select>
      </div>
      <div>
        <label for="refreshMs">Refresh (ms)</label>
        <input id="refreshMs" type="number" min="200" step="100" value="__REFRESH_MS__">
      </div>
      <div class="auto-wrap">
        <input id="autoRefresh" type="checkbox" checked>
        <label for="autoRefresh" style="margin: 0;">Auto refresh</label>
      </div>
      <div>
        <label>&nbsp;</label>
        <button id="refreshNow" type="button">Refresh now</button>
      </div>
    </section>

    <section class="cards">
      <article class="card">
        <div class="label">Status</div>
        <div class="value" id="statusValue">-</div>
        <div class="meta" id="statusMeta">&nbsp;</div>
      </article>
      <article class="card">
        <div class="label">Iteration</div>
        <div class="value" id="iterationValue">0</div>
        <div class="meta" id="iterationMeta">&nbsp;</div>
      </article>
      <article class="card">
        <div class="label">Build Progress</div>
        <div class="value" id="progressValue">0/0</div>
        <div class="meta" id="progressMeta">&nbsp;</div>
      </article>
      <article class="card">
        <div class="label">QA Gate</div>
        <div class="value" id="qaValue">-</div>
        <div class="meta" id="qaMeta">&nbsp;</div>
      </article>
      <article class="card">
        <div class="label">Tools Called</div>
        <div class="value" id="toolsValue">0</div>
        <div class="meta" id="toolsMeta">&nbsp;</div>
      </article>
    </section>

    <section class="panel" id="treePanel">
      <h2>Tree View</h2>
      <div id="treeContent" class="tree-container">
        <div class="tree-empty">No dispatches yet</div>
      </div>
    </section>

    <section class="panel">
      <h2>Agent Exchanges</h2>
      <table>
        <thead>
          <tr>
            <th>Iter</th>
            <th>Agent</th>
            <th>Action</th>
            <th>Topic</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody id="sharedKnowledgeBody"></tbody>
      </table>
    </section>

    <section class="panel">
      <h2>Agent Reasoning</h2>
      <table>
        <thead>
          <tr>
            <th>Iter</th>
            <th>Agent</th>
            <th>Model</th>
            <th>Input</th>
            <th>Output</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody id="agentReasoningBody"></tbody>
      </table>
    </section>

    <section class="grid">
      <section class="panel">
        <h2>Current Activity</h2>
        <table>
          <thead>
            <tr>
              <th>Iter</th>
              <th>Agent</th>
              <th>Working on</th>
            </tr>
          </thead>
          <tbody id="currentActivityBody"></tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Tool Usage</h2>
        <table>
          <thead>
            <tr>
              <th>Tool Name</th>
              <th>Calls</th>
            </tr>
          </thead>
          <tbody id="toolUsageBody"></tbody>
        </table>
      </section>
    </section>

    <section class="panel">
      <h2>Event Log</h2>
      <table>
        <thead>
          <tr>
            <th>Time (UTC)</th>
            <th>Type</th>
            <th>Iter</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody id="eventLogBody"></tbody>
      </table>
      <p id="errorBox" class="error"></p>
    </section>

  </main>

  <script>
    const runSelect = document.getElementById("runSelect");
    const refreshMsInput = document.getElementById("refreshMs");
    const autoRefresh = document.getElementById("autoRefresh");
    const refreshNow = document.getElementById("refreshNow");
    const errorBox = document.getElementById("errorBox");

    let refreshHandle = null;

    function fmt(value) {
      if (value === null || value === undefined || value === "") return "-";
      return String(value);
    }

    function setText(id, value) {
      const node = document.getElementById(id);
      if (node) node.textContent = fmt(value);
    }

    function toStatusBadge(status) {
      const normalized = String(status || "running").toLowerCase();
      return `<span class="status ${normalized}">${normalized}</span>`;
    }

    function renderRows(bodyId, rows, columns, emptyText, expandableMap) {
      const body = document.getElementById(bodyId);
      if (!body) return;
      body.innerHTML = "";
      if (!rows || rows.length === 0) {
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = columns.length;
        td.textContent = emptyText;
        tr.appendChild(td);
        body.appendChild(tr);
        return;
      }
      rows.forEach((row, idx) => {
        const tr = document.createElement("tr");
        tr.style.animationDelay = `${Math.min(idx, 10) * 35}ms`;
        columns.forEach((col) => {
          const td = document.createElement("td");
          const fullKey = expandableMap && expandableMap[col];
          const fullText = fullKey ? fmt(row[fullKey]) : null;
          const summary = fmt(row[col]);
          if (fullText && fullText.length > summary.length) {
            td.className = "expandable";
            td.innerHTML = `<span class="summary-text">${escapeHtml(summary)}</span><div class="full-text">${escapeHtml(fullText)}</div>`;
            td.addEventListener("click", () => td.classList.toggle("expanded"));
          } else {
            td.textContent = summary;
          }
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
    }

    function escapeHtml(text) {
      const div = document.createElement("div");
      div.textContent = text;
      return div.innerHTML;
    }

    function renderChips(id, items) {
      const node = document.getElementById(id);
      if (!node) return;
      node.innerHTML = "";
      const keys = Object.keys(items || {});
      if (keys.length === 0) {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = "No events";
        node.appendChild(chip);
        return;
      }
      keys.forEach((key) => {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = `${key}: ${items[key]}`;
        node.appendChild(chip);
      });
    }

    function renderRunOptions(availableRunIds, selectedRunId) {
      const previous = runSelect.value;
      runSelect.innerHTML = "";
      const autoOption = document.createElement("option");
      autoOption.value = "";
      autoOption.textContent = "Latest run (auto)";
      runSelect.appendChild(autoOption);

      (availableRunIds || []).forEach((runId) => {
        const option = document.createElement("option");
        option.value = runId;
        option.textContent = runId;
        runSelect.appendChild(option);
      });

      if (previous && (availableRunIds || []).includes(previous)) {
        runSelect.value = previous;
      } else if (selectedRunId && (availableRunIds || []).includes(selectedRunId)) {
        runSelect.value = selectedRunId;
      } else {
        runSelect.value = "";
      }
    }

    // ── Tree View ──
    function renderTreeView(exchanges) {
      const container = document.getElementById("treeContent");
      if (!container) return;
      const dispatches = (exchanges || []).filter(e => e.exchange_type === "dispatch");
      const results = (exchanges || []).filter(e => e.exchange_type === "dispatch_result");
      if (dispatches.length === 0) {
        container.innerHTML = '<div class="tree-empty">No dispatches yet</div>';
        return;
      }
      // Group by cycle
      const byCycle = {};
      dispatches.forEach(d => {
        const cid = d.cycle_id ?? "?";
        if (!byCycle[cid]) byCycle[cid] = [];
        byCycle[cid].push(d);
      });
      const resultMap = {};
      results.forEach(r => {
        const key = `${r.cycle_id}_${r.dispatch_number}`;
        resultMap[key] = r;
      });

      let html = "";
      Object.keys(byCycle).sort((a, b) => Number(a) - Number(b)).forEach(cid => {
        const group = byCycle[cid];
        html += `<div class="tree-root">`;
        html += `<div class="tree-node">`;
        html += `<span class="tree-dot coordinator"></span>`;
        html += `<div><span class="tree-label">Iteration ${escapeHtml(String(cid))} — Coordinator</span></div>`;
        html += `</div>`;
        html += `<div class="tree-branch">`;

        group.forEach(d => {
          const dn = d.dispatch_number;
          const role = d.to_agent || d.key || "agent";
          const task = d.task_summary || d.value_summary || "";
          const resultKey = `${cid}_${dn}`;
          const result = resultMap[resultKey];
          const hasFailed = result && (result.value_summary || "").includes("[dispatch error");
          const dotClass = result ? (hasFailed ? "failed" : "agent") : "coordinator";

          html += `<div class="tree-node">`;
          html += `<span class="tree-dot ${dotClass}"></span>`;
          html += `<div>`;
          html += `<span class="tree-label">${escapeHtml(role)}</span>`;
          if (task) {
            html += `<div class="tree-detail">${escapeHtml(task.substring(0, 200))}</div>`;
          }
          if (result && result.value_summary) {
            const rv = result.value_summary;
            const preview = rv.length > 200 ? rv.substring(0, 200) + "..." : rv;
            html += `<div class="tree-detail" style="color: var(--ink); margin-top: 3px;">${escapeHtml(preview)}</div>`;
          }
          html += `</div></div>`;
        });

        html += `</div></div>`;
      });
      container.innerHTML = html;
    }

    function renderSnapshot(snapshot) {
      renderRunOptions(snapshot.available_run_ids || [], snapshot.selected_run_id || "");

      const run = snapshot.run || {};
      const tasks = snapshot.tasks || {};
      const statusText = (run.status || "running").toLowerCase();

      // Status card
      const statusNode = document.getElementById("statusValue");
      statusNode.innerHTML = toStatusBadge(run.status || "running");
      const runId = snapshot.selected_run_id || "";
      const statusLabel = statusText === "completed" ? "done" : "running";
      setText("statusMeta", runId ? `${statusLabel} · ${runId}` : statusLabel);

      // Iteration card
      const iterCount = snapshot.cycle_count || 0;
      setText("iterationValue", iterCount);
      const llmCount = snapshot.event_counts?.llm_call || 0;
      setText("iterationMeta", `${tasks.started || 0} tasks · ${llmCount} LLM calls`);

      // Build Progress card
      setText("progressValue", `${tasks.completed || 0}/${tasks.started || 0}`);
      setText("progressMeta", `failed: ${tasks.failed || 0}  in-progress: ${tasks.in_progress || 0}`);

      // QA Gate card
      const evalStatus = run.evaluation_status || snapshot.latest_gate?.overall_status || "-";
      const qaNode = document.getElementById("qaValue");
      qaNode.innerHTML = toStatusBadge(evalStatus);
      setText("qaMeta", run.evaluation_action || snapshot.latest_gate?.recommended_action || "-");

      // Hero subtitle — iteration count and status
      setText("heroMeta", `Iteration ${iterCount} — ${statusText}`);

      // Tree view
      const exchanges = snapshot.agent_exchanges || [];
      renderTreeView(exchanges);

      // Agent Exchanges table (detail view)
      renderRows(
        "sharedKnowledgeBody",
        exchanges.map((item) => ({
          cycle_id: item.cycle_id ?? "-",
          from_agent: item.from_agent || "-",
          exchange_type: item.exchange_type || "-",
          key: item.key || item.to_agent || "-",
          value_summary: item.value_summary || item.task_summary || "-",
        })),
        ["cycle_id", "from_agent", "exchange_type", "key", "value_summary"],
        "No exchanges yet"
      );

      // Agent Reasoning (was LLM Calls) — always expanded, no toggle
      renderRows(
        "agentReasoningBody",
        (snapshot.llm_calls || []).map((item) => ({
          cycle_id: item.cycle_id ?? "-",
          agent: item.agent || "-",
          model: item.model || "-",
          message_summary: item.message_summary || "-",
          response_summary: item.response_summary || "-",
          duration_ms: item.duration_ms != null ? item.duration_ms + " ms" : "-",
        })),
        ["cycle_id", "agent", "model", "message_summary", "response_summary", "duration_ms"],
        "No agent reasoning yet"
      );

      // Current Activity (was Active Tasks)
      renderRows(
        "currentActivityBody",
        (snapshot.active_tasks || []).map((task) => ({
          cycle_id: task.cycle_id ?? "-",
          agent_role: task.agent_role || "-",
          objective: task.objective || "-",
        })),
        ["cycle_id", "agent_role", "objective"],
        "No active tasks"
      );

      // Event Log (was Recent Events)
      renderRows(
        "eventLogBody",
        (snapshot.recent_events || []).map((event) => ({
          timestamp_utc: event.timestamp_utc || "-",
          event_type: event.event_type || "-",
          cycle_id: event.cycle_id ?? "-",
          summary: event.summary || "",
        })),
        ["timestamp_utc", "event_type", "cycle_id", "summary"],
        "No events yet"
      );

      // Tools Called card
      const tools = snapshot.tools || {};
      setText("toolsValue", tools.called || 0);
      setText("toolsMeta", `denied: ${tools.denied || 0}  errors: ${tools.errors || 0}`);

      // Tool Usage table
      renderRows(
        "toolUsageBody",
        (tools.top_called || []).map((item) => ({
          tool_name: item.tool_name || "-",
          count: item.count || 0,
        })),
        ["tool_name", "count"],
        "No tools yet"
      );

      // Learnings (insights from agent exchanges)
      renderRows(
        "learningsBody",
        (snapshot.agent_exchanges || [])
          .filter((item) => {
            const etype = (item.exchange_type || "").toLowerCase();
            const key = (item.key || "").toLowerCase();
            return etype.includes("share_insight") && key.startsWith("learn.");
          })
          .map((item) => ({
            cycle_id: item.cycle_id ?? "-",
            key: item.key || "-",
            value_summary: item.value_summary || "-",
          })),
        ["cycle_id", "key", "value_summary"],
        "No learnings yet"
      );

    }

    async function fetchSnapshot() {
      const params = new URLSearchParams();
      if (runSelect.value) params.set("run_id", runSelect.value);
      params.set("recent_limit", "80");
      params.set("max_events", "8000");

      const response = await fetch(`/api/snapshot?${params.toString()}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Snapshot request failed with status ${response.status}`);
      }
      return response.json();
    }

    async function refreshDashboard() {
      try {
        const snapshot = await fetchSnapshot();
        renderSnapshot(snapshot);
        errorBox.style.display = "none";
      } catch (error) {
        errorBox.textContent = error instanceof Error ? error.message : String(error);
        errorBox.style.display = "block";
      }
    }

    function scheduleRefresh() {
      if (refreshHandle !== null) {
        clearInterval(refreshHandle);
        refreshHandle = null;
      }
      if (!autoRefresh.checked) {
        return;
      }
      const refreshMs = Math.max(200, Number.parseInt(refreshMsInput.value || "1000", 10));
      refreshHandle = setInterval(refreshDashboard, refreshMs);
    }

    autoRefresh.addEventListener("change", scheduleRefresh);
    refreshMsInput.addEventListener("change", scheduleRefresh);
    runSelect.addEventListener("change", refreshDashboard);
    refreshNow.addEventListener("click", refreshDashboard);

    scheduleRefresh();
    refreshDashboard();
  </script>
</body>
</html>
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local live dashboard for autonomy events.")
    parser.add_argument("--events-path", default="data/memory/web_autonomy_events.ndjson")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--max-events", type=int, default=8000)
    parser.add_argument("--recent-limit", type=int, default=80)
    parser.add_argument("--refresh-ms", type=int, default=1200)
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument(
        "--workspace",
        default=str(REPO_ROOT / "workspace"),
        help="Path to workspace directory for live preview (default: workspace/)",
    )
    return parser.parse_args()


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class DashboardServer(ThreadingHTTPServer):
    """HTTP server with immutable dashboard runtime settings."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        *,
        events_path: Path,
        max_events: int,
        recent_limit: int,
        refresh_ms: int,
        workspace: Optional[Path] = None,
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.events_path = events_path
        self.max_events = max_events
        self.recent_limit = recent_limit
        self.refresh_ms = refresh_ms
        self.workspace = workspace


class DashboardHandler(BaseHTTPRequestHandler):
    """Serve dashboard UI and snapshot API endpoints."""

    server: DashboardServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_index()
            return
        if parsed.path == "/api/snapshot":
            self._serve_snapshot(parsed.query)
            return
        if parsed.path == "/healthz":
            self._send_json({"status": "ok"})
            return
        if parsed.path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "not found")

    def log_message(self, fmt: str, *args: Any) -> None:
        del fmt, args

    def _serve_index(self) -> None:
        html = HTML_TEMPLATE.replace("__REFRESH_MS__", str(self.server.refresh_ms))
        payload = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _serve_snapshot(self, query: str) -> None:
        try:
            args = parse_qs(query, keep_blank_values=False)
            run_id = _first(args, "run_id")
            if run_id == "":
                run_id = None

            max_events = _safe_int(_first(args, "max_events"), self.server.max_events)
            recent_limit = _safe_int(_first(args, "recent_limit"), self.server.recent_limit)
            snapshot = build_snapshot_from_ndjson(
                self.server.events_path,
                run_id=run_id,
                max_events=max(1, max_events),
                recent_limit=max(1, recent_limit),
            )
            self._send_json(snapshot)
        except Exception as exc:
            self._send_json(
                {"error": str(exc), "status": "error"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _send_json(self, payload: Dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _first(values: Dict[str, list[str]], key: str) -> Optional[str]:
    row = values.get(key)
    if not row:
        return None
    return row[0]


def main() -> None:
    args = _parse_args()
    events_path = Path(args.events_path)
    workspace_path = Path(args.workspace)
    workspace_resolved = workspace_path.resolve() if workspace_path.is_dir() else None

    server = DashboardServer(
        (args.host, args.port),
        DashboardHandler,
        events_path=events_path,
        max_events=max(1, int(args.max_events)),
        recent_limit=max(1, int(args.recent_limit)),
        refresh_ms=max(200, int(args.refresh_ms)),
        workspace=workspace_resolved,
    )
    url = f"http://{args.host}:{args.port}"
    print("=" * 64)
    print("BUILD DASHBOARD")
    print("=" * 64)
    print(f"URL:       {url}")
    print(f"Events:    {events_path}")
    if workspace_resolved:
        print(f"Preview:   {url}/workspace/ (live preview embedded)")
    else:
        print(f"Preview:   disabled (workspace dir not found: {workspace_path})")
    print("Press Ctrl+C to stop.")
    print("=" * 64)

    if args.open_browser:
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
