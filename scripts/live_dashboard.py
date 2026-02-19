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

add_repo_root_to_path(__file__)

from src.framework.observability.dashboard import build_snapshot_from_ndjson


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Autonomy Live Dashboard</title>
  <style>
    :root {
      --ink: #0f2431;
      --ink-soft: #446071;
      --surface: rgba(255, 255, 255, 0.84);
      --surface-strong: rgba(255, 255, 255, 0.94);
      --line: #c9dbe3;
      --accent: #00897b;
      --accent-2: #f57c00;
      --danger: #c62828;
      --ok: #2e7d32;
      --warn: #ed6c02;
      --radius: 16px;
      --shadow: 0 18px 48px rgba(0, 0, 0, 0.10);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "Space Grotesk", "Avenir Next", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 14% 18%, #d7f2ec 0%, transparent 32%),
        radial-gradient(circle at 82% 16%, #ffe5d2 0%, transparent 28%),
        linear-gradient(145deg, #ecf3f8 0%, #eef6ee 100%);
      min-height: 100vh;
    }
    .frame {
      width: min(1320px, 96vw);
      margin: 18px auto 28px;
      display: grid;
      gap: 12px;
    }
    .hero {
      background: linear-gradient(120deg, rgba(0, 137, 123, 0.17), rgba(245, 124, 0, 0.18));
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 16px;
      box-shadow: var(--shadow);
      animation: rise 480ms ease-out both;
    }
    .hero h1 { margin: 0; font-size: clamp(20px, 2.7vw, 32px); letter-spacing: 0.02em; }
    .hero p { margin: 7px 0 0; color: var(--ink-soft); font-size: 13px; }
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
    .controls label { display: block; font-size: 11px; text-transform: uppercase; color: var(--ink-soft); margin-bottom: 4px; }
    select, button, input[type="number"] {
      width: 100%;
      padding: 9px 11px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--surface-strong);
      color: var(--ink);
      font-weight: 600;
    }
    button {
      cursor: pointer;
      background: linear-gradient(145deg, #f8fffe, #fff4ea);
      border-color: #b7ced9;
    }
    .auto-wrap {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 10px;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 12px;
      box-shadow: var(--shadow);
      animation: rise 520ms ease-out both;
    }
    .card:nth-child(2) { animation-delay: 60ms; }
    .card:nth-child(3) { animation-delay: 120ms; }
    .card:nth-child(4) { animation-delay: 180ms; }
    .card:nth-child(5) { animation-delay: 240ms; }
    .card:nth-child(6) { animation-delay: 300ms; }
    .label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--ink-soft);
      margin-bottom: 5px;
    }
    .value {
      font-size: clamp(19px, 2.4vw, 29px);
      font-weight: 700;
      line-height: 1.05;
    }
    .meta { font-size: 12px; color: var(--ink-soft); margin-top: 5px; }
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
      padding: 10px 12px;
      font-size: 14px;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      color: var(--ink-soft);
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.58);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    th, td {
      text-align: left;
      border-bottom: 1px solid #ddeaf0;
      padding: 8px 10px;
      vertical-align: top;
      word-break: break-word;
    }
    tbody tr {
      animation: rowIn 220ms ease-out both;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      padding: 10px;
    }
    .chip {
      border: 1px solid #bad4de;
      border-radius: 999px;
      padding: 5px 9px;
      font-size: 12px;
      background: rgba(255, 255, 255, 0.75);
      white-space: nowrap;
    }
    .status {
      display: inline-block;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .status.running { color: #155a58; background: #d4f3ef; }
    .status.completed { color: #1f6f33; background: #dbf2df; }
    .status.stopped { color: #7a1f1f; background: #f8dbdb; }
    .status.paused { color: #8f5600; background: #ffe8c5; }
    .status.warn { color: #8f5600; background: #ffe8c5; }
    .status.fail { color: #7a1f1f; background: #f8dbdb; }
    .status.pass { color: #1f6f33; background: #dbf2df; }
    .error {
      margin: 0;
      padding: 8px 10px;
      color: #8e2d2d;
      font-size: 12px;
      border-top: 1px solid #efc5c5;
      background: #ffecec;
      display: none;
    }
    @keyframes rise {
      from { transform: translateY(6px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }
    @keyframes rowIn {
      from { opacity: 0; transform: translateX(4px); }
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
      <h1>Autonomy Run Live Dashboard</h1>
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
        <div class="label">Run Status</div>
        <div class="value" id="statusValue">-</div>
        <div class="meta" id="runIdMeta">run: -</div>
      </article>
      <article class="card">
        <div class="label">Events</div>
        <div class="value" id="eventsValue">0</div>
        <div class="meta" id="eventsMeta">source: 0</div>
      </article>
      <article class="card">
        <div class="label">Cycles</div>
        <div class="value" id="cyclesValue">0</div>
        <div class="meta" id="cycleMeta">tasked: 0</div>
      </article>
      <article class="card">
        <div class="label">Tasks</div>
        <div class="value" id="tasksValue">0/0</div>
        <div class="meta" id="tasksMeta">failed: 0 in-progress: 0</div>
      </article>
      <article class="card">
        <div class="label">Tools</div>
        <div class="value" id="toolsValue">0</div>
        <div class="meta" id="toolsMeta">denied: 0 errors: 0</div>
      </article>
      <article class="card">
        <div class="label">Evaluation</div>
        <div class="value" id="evalValue">-</div>
        <div class="meta" id="evalMeta">action: -</div>
      </article>
    </section>

    <section class="grid">
      <section class="panel">
        <h2>Cycle Outcomes</h2>
        <table>
          <thead>
            <tr>
              <th>Cycle</th>
              <th>Total</th>
              <th>Done</th>
              <th>Failed</th>
              <th>Eval</th>
              <th>Action</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody id="cyclesBody"></tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Gate Decisions</h2>
        <table>
          <thead>
            <tr>
              <th>Gate</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="gatesBody"></tbody>
        </table>
      </section>
    </section>

    <section class="grid">
      <section class="panel">
        <h2>Active Tasks</h2>
        <table>
          <thead>
            <tr>
              <th>Task ID</th>
              <th>Cycle</th>
              <th>Role</th>
              <th>Objective</th>
            </tr>
          </thead>
          <tbody id="activeTasksBody"></tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Event Mix</h2>
        <div id="eventChips" class="chips"></div>
        <h2 style="border-top: 1px solid var(--line);">Top Tools</h2>
        <table>
          <thead>
            <tr>
              <th>Tool</th>
              <th>Calls</th>
            </tr>
          </thead>
          <tbody id="toolsBody"></tbody>
        </table>
      </section>
    </section>

    <section class="panel">
      <h2>Recent Events</h2>
      <table>
        <thead>
          <tr>
            <th>Seq</th>
            <th>Time (UTC)</th>
            <th>Type</th>
            <th>Cycle</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody id="recentBody"></tbody>
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

    function renderRows(bodyId, rows, columns, emptyText) {
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
          td.textContent = fmt(row[col]);
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
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

    function renderSnapshot(snapshot) {
      renderRunOptions(snapshot.available_run_ids || [], snapshot.selected_run_id || "");

      const run = snapshot.run || {};
      const tasks = snapshot.tasks || {};
      const tools = snapshot.tools || {};

      const statusNode = document.getElementById("statusValue");
      statusNode.innerHTML = toStatusBadge(run.status || "running");

      setText("runIdMeta", `run: ${snapshot.selected_run_id || "<none>"}`);
      setText("eventsValue", snapshot.run_event_count || 0);
      setText("eventsMeta", `source: ${snapshot.source_event_count || 0}`);
      setText("cyclesValue", snapshot.cycle_count || 0);
      setText("cycleMeta", `policy violations: ${snapshot.policy_violations || 0}`);
      setText("tasksValue", `${tasks.completed || 0}/${tasks.started || 0}`);
      setText(
        "tasksMeta",
        `failed: ${tasks.failed || 0} in-progress: ${tasks.in_progress || 0}`
      );
      setText("toolsValue", tools.called || 0);
      setText("toolsMeta", `denied: ${tools.denied || 0} errors: ${tools.errors || 0}`);

      const evalStatus = run.evaluation_status || snapshot.latest_gate?.overall_status || "-";
      const evalNode = document.getElementById("evalValue");
      evalNode.innerHTML = toStatusBadge(evalStatus);
      setText(
        "evalMeta",
        `action: ${run.evaluation_action || snapshot.latest_gate?.recommended_action || "-"}`
      );

      setText(
        "heroMeta",
        `${snapshot.events_path || ""} | generated: ${snapshot.generated_at_utc || "-"}`
      );

      renderRows(
        "cyclesBody",
        (snapshot.cycles || []).map((item) => ({
          cycle_id: item.cycle_id,
          total_tasks: item.total_tasks ?? item.tasks_started ?? "-",
          completed_count: item.completed_count ?? item.tasks_completed ?? 0,
          failed_count: item.failed_count ?? item.tasks_failed ?? 0,
          evaluation_status: item.evaluation_status || "-",
          termination_action: item.termination_action || "-",
          termination_reason: item.termination_reason || "-",
        })),
        [
          "cycle_id",
          "total_tasks",
          "completed_count",
          "failed_count",
          "evaluation_status",
          "termination_action",
          "termination_reason",
        ],
        "No cycles yet"
      );

      renderRows(
        "gatesBody",
        (snapshot.latest_gate?.gates || []).map((gate) => ({
          gate_name: gate.gate_name || "-",
          gate_status: gate.gate_status || "-",
          recommended_action: gate.recommended_action || "-",
        })),
        ["gate_name", "gate_status", "recommended_action"],
        "No gate decisions yet"
      );

      renderRows(
        "activeTasksBody",
        (snapshot.active_tasks || []).map((task) => ({
          task_id: task.task_id || "-",
          cycle_id: task.cycle_id ?? "-",
          agent_role: task.agent_role || "-",
          objective: task.objective || "-",
        })),
        ["task_id", "cycle_id", "agent_role", "objective"],
        "No active tasks"
      );

      renderRows(
        "toolsBody",
        (tools.top_called || []).map((tool) => ({
          tool_name: tool.tool_name || "-",
          count: tool.count || 0,
        })),
        ["tool_name", "count"],
        "No tool calls"
      );

      renderRows(
        "recentBody",
        (snapshot.recent_events || []).map((event) => ({
          sequence: event.sequence ?? "-",
          timestamp_utc: event.timestamp_utc || "-",
          event_type: event.event_type || "-",
          cycle_id: event.cycle_id ?? "-",
          summary: event.summary || "",
        })),
        ["sequence", "timestamp_utc", "event_type", "cycle_id", "summary"],
        "No events yet"
      );

      renderChips("eventChips", snapshot.event_counts || {});
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
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.events_path = events_path
        self.max_events = max_events
        self.recent_limit = recent_limit
        self.refresh_ms = refresh_ms


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

    server = DashboardServer(
        (args.host, args.port),
        DashboardHandler,
        events_path=events_path,
        max_events=max(1, int(args.max_events)),
        recent_limit=max(1, int(args.recent_limit)),
        refresh_ms=max(200, int(args.refresh_ms)),
    )
    url = f"http://{args.host}:{args.port}"
    print("=" * 64)
    print("AUTONOMY LIVE DASHBOARD")
    print("=" * 64)
    print(f"URL: {url}")
    print(f"Events path: {events_path}")
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
