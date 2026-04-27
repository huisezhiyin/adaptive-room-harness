# Development

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Checks

```bash
.venv/bin/python -m ruff check src tests
.venv/bin/python -m pytest -q
```

## Local Smoke

```bash
.venv/bin/room init --workspace /tmp/room-smoke --task "Smoke test"
.venv/bin/room list --workspace /tmp/room-smoke
.venv/bin/room serve --workspace /tmp/room-smoke --port 8765
```

Open `http://127.0.0.1:8765`.

## Design Constraints

- Keep the room local-first and file-backed.
- Keep `room serve` read-only.
- Keep non-main participants advisory by default.
- Do not commit `.room/`, `.agent-memory/`, virtualenvs, caches, or generated runtime traces.
