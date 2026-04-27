# Adaptive Room Harness

Adaptive Room Harness is a local-first multi-agent discussion room for Codex-style coding workflows.

It lets a main agent keep ownership of the task while waking a small peer room when work is complex, risky, or ambiguous. The room records the agent discussion, writes durable artifacts, and produces a concise `main_agent_reference.json` packet that the main agent can use as advisory input.

This is an early public alpha: useful enough to run locally, intentionally small, and still rough around the edges.

## Keywords

Codex CLI, agentic coding, multi-agent collaboration, local-first AI tools, agent room, peer review, advisory planning, developer workflow automation.

## Why This Exists

Most coding-agent work should stay simple: one main agent, one workspace, one clear owner. But harder tasks often benefit from a second pass: independent drafting, review, revision, risk checks, and a durable summary that can be inspected later.

Adaptive Room Harness is the small local harness for that middle ground. It does not try to become a general autonomous multi-agent platform. It gives the main agent a room it can wake when useful, then turns the discussion into artifacts the main agent can actually use.

## What Works Today

- `room codex-ask` triages a task and wakes two Codex CLI participants when useful.
- Same-capability participants use a deep collaboration chain by default: draft, review, revise, final check.
- Simple tasks stay in the main Codex session.
- Complex tasks create a room transcript, design notes, task notes, and `main_agent_reference.json`.
- `room serve` opens a read-only local web observer for rooms, discussion turns, and artifacts.
- Optional approval commands exist for stricter flows: `accept-plan`, `reject-plan`, and `execution-context`.

The main agent remains the writer, decider, and verifier. Other agents provide discussion and reference material.

## Prerequisites

- Python 3.11+
- A working Codex CLI install for commands that wake Codex participants, such as `room codex-ask`, `room wake`, and `room play`
- Codex CLI authentication already configured locally

The test suite uses a fake Codex executable, so development checks do not require live Codex calls.

## Install

```bash
git clone <repo-url>
cd adaptive-room-harness
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Check the CLI:

```bash
.venv/bin/room version
```

## Quickstart

Run the observer UI in one terminal:

```bash
.venv/bin/room serve --workspace . --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

In another terminal, ask for help on a complex task:

```bash
.venv/bin/room codex-ask \
  --workspace . \
  --task "Design a risky architecture migration with rollback concerns."
```

For a complex task, the room wakes two Codex participants, records their discussion, and writes:

```text
.room/rooms/<room_id>/
  transcript.jsonl
  artifacts/
    main_agent_reference.json
    design.md
    tasks.md
    room_synthesis.json
    approval_state.json
    execution_plan.json
```

The normal alpha workflow is:

```text
main agent receives task
  -> room codex-ask
  -> simple task: continue solo
  -> complex task: wake two Codex participants
  -> agent A drafts, agent B reviews, agent A revises, agent B final-checks
  -> room writes main_agent_reference.json
  -> main agent reads the reference, decides, implements, verifies
```

In other words: the room advises; the main agent owns the work.

## Core Commands

```bash
room ask --workspace <path> --task "<task>"
room host-ask --workspace <path> --task "<task>"
room codex-ask --workspace <path> --task "<task>"
room reference-context --workspace <path> --room <room_id>
room serve --workspace <path> --port 8765
room wake --workspace <path> --task "<task>" --goal "<goal>"
room play --workspace <path> --task "<task>" --rounds 1
```

The default collaboration pattern is `draft_review_revise`. Use `--collaboration-pattern parallel_opinion` when you intentionally want the older two-independent-opinions behavior.

Manual room operations are also available:

```bash
room init --workspace <path> --task "<task>"
room triage --workspace <path> --room <room_id>
room attach --workspace <path> --room <room_id> --kind agent --id reviewer
room say --workspace <path> --room <room_id> --speaker codex_main --content "..."
room add-evidence --workspace <path> --room <room_id> --source file:...
room decide --workspace <path> --room <room_id> --decision "..." --why "..."
room report --workspace <path> --room <room_id>
```

Optional approval flow:

```bash
room accept-plan --workspace <path> --room <room_id>
room reject-plan --workspace <path> --room <room_id> --reason "..."
room execution-context --workspace <path> --room <room_id>
```

## Observer UI

`room serve` is read-only. It watches local room files and shows:

- room list and status
- recent discussion turns
- `main_agent_reference.json`
- design and task artifacts
- synthesis, approval state, execution plan, and reports

The first version uses browser polling. It does not stream partial tokens yet; completed agent turns appear as the room files update.

## Codex CLI Notes

The Codex adapter runs `codex exec` for each participant. By default it uses `gpt-5.4` for Codex CLI compatibility.

Override the model with:

```bash
ROOM_CODEX_MODEL=<model> room codex-ask --workspace . --task "..."
```

or:

```bash
room codex-ask --workspace . --task "..." --model <model>
```

## Development

```bash
.venv/bin/python -m ruff check src tests
.venv/bin/python -m pytest -q
```

The tests use a fake Codex executable, so they do not require network access or a real Codex CLI session.

## Non-Goals

- Not a general multi-agent platform.
- Not an autonomous infinite loop.
- Not a system where multiple agents write to the same workspace by default.
- Not a replacement for the main agent's judgment.

## Docs

- [Quick Demo](docs/QUICK_DEMO.md)
- [Technical Architecture](docs/TECHNICAL_ARCHITECTURE.md)
- [Product Direction](docs/PRODUCT_DIRECTION.md)
- [Usable Stage Roadmap](docs/USABLE_STAGE_ROADMAP.md)
- [Idea Doc v2](docs/IDEA_DOC_V2.md)

## License

MIT
