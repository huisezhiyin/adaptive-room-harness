# Quick Demo

This demo shows the current Public Alpha loop:

```text
complex task -> two Codex participants discuss -> room writes reference packet -> main agent uses it
```

## 1. Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## 2. Start The Observer

```bash
.venv/bin/room serve --workspace . --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

The observer is read-only. It shows room status, recent discussion turns, and artifacts.

## 3. Run A Complex Ask

In a second terminal:

```bash
.venv/bin/room codex-ask \
  --workspace . \
  --task "Design a risky architecture migration with rollback concerns."
```

Expected behavior:

- A room is created under `.room/rooms/<room_id>/`.
- Two Codex participants are invoked with `codex exec`.
- The default `draft_review_revise` pattern produces draft, review, revise, and final-check turns.
- Their completed turns are appended to `transcript.jsonl`.
- The observer page updates through polling.
- `artifacts/main_agent_reference.json` is written and opened by default in the UI.

## 4. Inspect The Reference Packet

```bash
.venv/bin/room reference-context --workspace . --room <room_id>
```

The packet is advisory only. The main agent decides what to use, implements the final changes, and verifies them.

To try the older two-independent-opinions behavior:

```bash
.venv/bin/room codex-ask \
  --workspace . \
  --task "Compare two design options." \
  --collaboration-pattern parallel_opinion
```

## 5. Try A Simple Ask

```bash
.venv/bin/room codex-ask \
  --workspace . \
  --task "Rename a local variable."
```

Expected behavior:

- No Codex participants are woken.
- The response says the task can continue in the main session.

## Notes

- This alpha uses polling, not token streaming.
- The room does not directly edit the workspace.
- Tests use a fake Codex executable, so development checks do not require a live Codex call.
