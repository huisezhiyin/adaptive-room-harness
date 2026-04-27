from __future__ import annotations

import html
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from adaptive_room_harness.services import list_room_summaries, room_snapshot
from adaptive_room_harness.store import load_state, room_path

ARTIFACT_NAMES = [
    "main_agent_reference.json",
    "host_decision.json",
    "room_synthesis.json",
    "approval_state.json",
    "execution_plan.json",
    "wake_checkpoint.json",
    "design.md",
    "tasks.md",
    "room_summary.md",
]


def build_rooms_payload(workspace: Path) -> dict[str, object]:
    return {
        "workspace": str(workspace.resolve()),
        "rooms": list_room_summaries(workspace),
    }


def build_room_payload(workspace: Path, room_id: str) -> dict[str, object]:
    state = load_state(workspace, room_id)
    base = room_path(Path(state.workspace), state.room_id)
    artifacts: dict[str, object] = {}
    for name in ARTIFACT_NAMES:
        path = base / "artifacts" / name
        if not path.exists():
            continue
        content = path.read_text()
        if name.endswith(".json"):
            try:
                artifacts[name] = {"kind": "json", "content": json.loads(content)}
            except json.JSONDecodeError:
                artifacts[name] = {"kind": "text", "content": content}
        else:
            artifacts[name] = {"kind": "text", "content": content}

    report_path = base / "reports" / "final.md"
    if report_path.exists():
        artifacts["reports/final.md"] = {"kind": "text", "content": report_path.read_text()}

    return {
        **room_snapshot(state),
        "room_path": str(base),
        "artifacts": artifacts,
    }


def serve_observer(workspace: Path, host: str, port: int) -> None:
    workspace = workspace.resolve()
    handler = make_handler(workspace)
    server = ThreadingHTTPServer((host, port), handler)
    server.serve_forever()


def make_handler(workspace: Path) -> type[BaseHTTPRequestHandler]:
    class RoomObserverHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path == "/":
                self.respond_html(render_index_html(workspace))
                return
            if path == "/api/rooms":
                self.respond_json(build_rooms_payload(workspace))
                return
            if path.startswith("/api/rooms/"):
                room_id = unquote(path.removeprefix("/api/rooms/"))
                try:
                    self.respond_json(build_room_payload(workspace, room_id))
                except FileNotFoundError:
                    self.respond_json(
                        {"error": f"Room not found: {room_id}"},
                        status=HTTPStatus.NOT_FOUND,
                    )
                return
            self.respond_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

        def respond_html(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def respond_json(
            self,
            payload: dict[str, object],
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return RoomObserverHandler


def render_index_html(workspace: Path) -> str:
    title = "Adaptive Room Observer"
    workspace_label = html.escape(str(workspace))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f4ef;
      --panel: #ffffff;
      --ink: #1d2525;
      --muted: #687373;
      --line: #d9ddd7;
      --accent: #1f7a6a;
      --accent-2: #8f3f52;
      --code: #172121;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 0 18px;
      border-bottom: 1px solid var(--line);
      background: #fbfaf6;
    }}
    h1 {{
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .workspace {{
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    main {{
      display: grid;
      grid-template-columns: minmax(220px, 280px) minmax(360px, 1fr) minmax(320px, 420px);
      height: calc(100vh - 56px);
      min-height: 520px;
    }}
    aside, section {{
      min-width: 0;
      overflow: auto;
      border-right: 1px solid var(--line);
    }}
    .right {{ border-right: 0; }}
    .pane-title {{
      position: sticky;
      top: 0;
      z-index: 2;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: rgba(251, 250, 246, 0.96);
      font-size: 12px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
    }}
    .room-row {{
      width: 100%;
      border: 0;
      border-bottom: 1px solid var(--line);
      background: transparent;
      padding: 13px 14px;
      text-align: left;
      cursor: pointer;
      color: var(--ink);
    }}
    .room-row:hover, .room-row.active {{ background: #ebe8df; }}
    .room-id {{ font-size: 13px; font-weight: 700; }}
    .room-task {{ margin-top: 6px; color: var(--muted); font-size: 12px; line-height: 1.35; }}
    .room-meta {{ margin-top: 8px; display: flex; gap: 7px; flex-wrap: wrap; }}
    .pill {{
      display: inline-flex;
      align-items: center;
      min-height: 20px;
      padding: 2px 7px;
      border-radius: 999px;
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 11px;
      background: #fffdf8;
    }}
    .conversation {{ padding: 14px 16px 26px; }}
    .turn {{
      margin-bottom: 14px;
      padding: 12px 13px;
      border: 1px solid var(--line);
      border-left: 4px solid var(--accent);
      background: var(--panel);
      border-radius: 8px;
    }}
    .turn:nth-child(even) {{ border-left-color: var(--accent-2); }}
    .speaker {{ font-size: 12px; font-weight: 700; color: var(--accent); }}
    .turn-body {{ margin-top: 8px; white-space: pre-wrap; line-height: 1.45; font-size: 13px; }}
    .artifact-list {{ padding: 14px 14px 26px; }}
    details {{
      margin-bottom: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      overflow: hidden;
    }}
    summary {{
      cursor: pointer;
      padding: 11px 12px;
      color: var(--ink);
      font-size: 13px;
      font-weight: 700;
    }}
    pre {{
      margin: 0;
      padding: 12px;
      overflow: auto;
      max-height: 420px;
      background: var(--code);
      color: #e7f0ed;
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
    }}
    .empty {{
      padding: 22px 16px;
      color: var(--muted);
      font-size: 13px;
    }}
    @media (max-width: 980px) {{
      main {{ grid-template-columns: 1fr; height: auto; }}
      aside, section {{ min-height: 360px; border-right: 0; border-bottom: 1px solid var(--line); }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <div class="workspace">{workspace_label}</div>
  </header>
  <main>
    <aside>
      <div class="pane-title">Rooms</div>
      <div id="rooms" class="empty">Loading rooms...</div>
    </aside>
    <section>
      <div class="pane-title">Discussion</div>
      <div id="conversation" class="empty">Select a room.</div>
    </section>
    <section class="right">
      <div class="pane-title">Results</div>
      <div id="artifacts" class="empty">No room selected.</div>
    </section>
  </main>
  <script>
    let currentRoom = null;
    async function fetchJson(url) {{
      const response = await fetch(url, {{ cache: "no-store" }});
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    }}
    function esc(value) {{
      return String(value ?? "").replace(/[&<>"']/g, ch => ({{
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }}[ch]));
    }}
    async function refreshRooms() {{
      const payload = await fetchJson("/api/rooms");
      const rooms = payload.rooms || [];
      const root = document.getElementById("rooms");
      if (!rooms.length) {{
        root.className = "empty";
        root.textContent = "No rooms yet.";
        return;
      }}
      root.className = "";
      root.innerHTML = rooms.map(room => {{
        const activeClass = room.room_id === currentRoom ? "active" : "";
        return `
        <button class="room-row ${{activeClass}}" data-room="${{esc(room.room_id)}}">
          <div class="room-id">${{esc(room.room_id)}}</div>
          <div class="room-task">${{esc(room.task)}}</div>
          <div class="room-meta">
            <span class="pill">${{esc(room.status)}}</span>
            <span class="pill">${{esc(room.mode)}}</span>
            <span class="pill">${{esc(room.collaboration_pattern)}}</span>
            <span class="pill">${{esc(room.turns)}} turns</span>
          </div>
        </button>
      `;
      }}).join("");
      root.querySelectorAll("[data-room]").forEach(button => {{
        button.addEventListener("click", () => {{
          currentRoom = button.dataset.room;
          refreshRooms();
          refreshRoom();
        }});
      }});
      if (!currentRoom && rooms[0]) {{
        currentRoom = rooms[0].room_id;
        refreshRooms();
        refreshRoom();
      }}
    }}
    async function refreshRoom() {{
      if (!currentRoom) return;
      const room = await fetchJson(`/api/rooms/${{encodeURIComponent(currentRoom)}}`);
      const turns = room.recent_transcript || [];
      const conversation = document.getElementById("conversation");
      if (!turns.length) {{
        conversation.className = "empty";
        conversation.textContent = "No discussion turns recorded yet.";
      }} else {{
        conversation.className = "conversation";
        conversation.innerHTML = turns.map(turn => `
          <article class="turn">
            <div class="speaker">${{esc(turn.speaker_id)}} · ${{esc(turn.type)}}</div>
            <div class="turn-body">${{esc(turn.content)}}</div>
          </article>
        `).join("");
      }}
      const artifacts = room.artifacts || {{}};
      const artifactRoot = document.getElementById("artifacts");
      const names = Object.keys(artifacts);
      if (!names.length) {{
        artifactRoot.className = "empty";
        artifactRoot.textContent = "No artifacts recorded yet.";
        return;
      }}
      artifactRoot.className = "artifact-list";
      artifactRoot.innerHTML = names.map(name => {{
        const item = artifacts[name];
        const content = item.kind === "json"
          ? JSON.stringify(item.content, null, 2)
          : item.content;
        const open = name === "main_agent_reference.json" ? " open" : "";
        return `
          <details${{open}}>
            <summary>${{esc(name)}}</summary>
            <pre>${{esc(content)}}</pre>
          </details>
        `;
      }}).join("");
    }}
    async function tick() {{
      try {{
        await refreshRooms();
        await refreshRoom();
      }} catch (error) {{
        console.error(error);
      }}
    }}
    tick();
    setInterval(tick, 2000);
  </script>
</body>
</html>
"""
