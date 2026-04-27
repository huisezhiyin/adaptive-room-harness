# Adaptive Room Harness

Adaptive Room Harness is a local-first multi-agent discussion room for coding-agent workflows.

It lets a main agent keep ownership of the task while waking a small peer room when work is complex, risky, or ambiguous. The room records the agent discussion, writes durable artifacts, and produces a concise `main_agent_reference.json` packet that the main agent can use as advisory input.

The room is runtime-neutral: each participant is backed by the configured adapter, such as `codex-cli`, `claude-cli`, or an Anthropic-compatible API. A requested runtime is authoritative for that wake cycle. If it fails, the room surfaces that failure instead of silently substituting another runtime.

This is an early public alpha: useful enough to run locally, intentionally small, and still rough around the edges.

## Keywords

coding agents, agentic coding, multi-agent collaboration, local-first AI tools, agent room, peer review, advisory planning, developer workflow automation, Codex CLI.

## Why This Exists

Most coding-agent work should stay simple: one main agent, one workspace, one clear owner. But harder tasks often benefit from a second pass: independent drafting, review, revision, risk checks, and a durable summary that can be inspected later.

Adaptive Room Harness is the small local harness for that middle ground. It does not try to become a general autonomous multi-agent platform. It gives the main agent a room it can wake when useful, then turns the discussion into artifacts the main agent can actually use.

The current alpha ships with Codex CLI, Claude Code CLI, and Anthropic-compatible API adapters. Codex-specific commands are convenience wrappers; they are not the room's identity or the only supported runtime.

## What Works Today

- `room play --profile <name>` wakes configured participants across supported runtimes.
- `room codex-ask` is a Codex-oriented convenience wrapper for local Codex workflows.
- Same-capability participants use a deep collaboration chain by default: draft, review, revise, final check.
- Simple tasks stay in the main host or agent session.
- Complex tasks create a room transcript, design notes, task notes, and `main_agent_reference.json`.
- `room serve` opens a read-only local web observer for rooms, discussion turns, and artifacts.
- Optional approval commands exist for stricter flows: `accept-plan`, `reject-plan`, and `execution-context`.

The main agent remains the writer, decider, and verifier. Other agents provide discussion and reference material.

## Prerequisites

- Python 3.11+
- At least one working runtime adapter for live participant calls, such as Codex CLI, Claude Code CLI, or an Anthropic-compatible API key
- Runtime authentication already configured locally for the adapters you choose

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

In another terminal, wake a configured room profile:

```bash
.venv/bin/room play \
  --workspace . \
  --task "Review a risky architecture migration with rollback concerns." \
  --profile cc-review
```

Or use the Codex-oriented convenience wrapper:

```bash
.venv/bin/room codex-ask \
  --workspace . \
  --task "Design a risky architecture migration with rollback concerns."
```

For a complex task, the room wakes the configured participants, records their discussion, and writes:

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
  -> room play --profile <name>
  -> simple task: continue solo
  -> complex task: wake configured participants
  -> participant A drafts, participant B reviews, participant A revises, participant B final-checks
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

## Claude Code And DeepSeek Runtimes

The Claude Code adapter runs `claude -p` in non-interactive mode:

```bash
room play \
  --workspace . \
  --task "Review this architecture plan." \
  --runtime claude-cli \
  --model sonnet \
  --collaboration-pattern parallel_opinion
```

Claude Code keeps its own authentication outside the repository. To route Claude Code through
DeepSeek's Anthropic-compatible API, set `ROOM_CLAUDE_PROVIDER=deepseek` in `.env`. The harness
maps that to the Claude Code variables documented by DeepSeek: `ANTHROPIC_BASE_URL`,
`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`,
`ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`, and
`CLAUDE_CODE_SUBAGENT_MODEL`. The adapter also passes those values through a temporary
`--settings` file so project-local DeepSeek configuration can override a stale global Claude Code
gateway without putting the API key on the command line.
Use `ROOM_CLAUDE_DEEPSEEK_MODEL=deepseek-v4-flash` for the Claude Code path when you want fast,
cheap advisory turns, while keeping `ROOM_ANTHROPIC_MODEL=deepseek-v4-pro[1m]` for direct
Anthropic-compatible API participants.

For project-local credentials, copy `.env.example` to `.env`. The CLI loads `<workspace>/.env`
before waking participants, and `.env` is ignored by Git:

```bash
cp .env.example .env
$EDITOR .env
```

The alpha can also wake participants through an Anthropic-compatible Messages API. The default endpoint is DeepSeek:

```bash
export DEEPSEEK_API_KEY=<your-key>

room play \
  --workspace . \
  --task "Review this architecture plan." \
  --runtime anthropic-api \
  --model deepseek-v4-pro \
  --collaboration-pattern parallel_opinion
```

The API key is read from the environment and is not written to room artifacts. Override the endpoint or key variable when using another Anthropic-compatible provider:

```bash
room play \
  --runtime anthropic-api \
  --anthropic-base-url https://api.deepseek.com/anthropic \
  --anthropic-api-key-env DEEPSEEK_API_KEY \
  --model deepseek-v4-pro \
  --task "..."
```

`room play` can mix runtimes per participant:

```bash
room play \
  --workspace . \
  --task "Codex drafts the implementation plan; DeepSeek reviews product value." \
  --collaboration-pattern parallel_opinion \
  --agent-a codex_planner \
  --agent-a-runtime codex-cli \
  --agent-a-model gpt-5.4 \
  --agent-b deepseek_reviewer \
  --agent-b-runtime anthropic-api \
  --agent-b-model deepseek-v4-pro
```

Participant-specific flags override the default `--runtime` and `--model` values for that
speaker. This first alpha slice keeps the mixed-runtime surface intentionally small:
`--agent-a-runtime`, `--agent-b-runtime`, `--agent-a-model`, `--agent-b-model`,
`--agent-a-bin`, `--agent-b-bin`, `--agent-a-api-base-url`, and `--agent-b-api-base-url`.

For repeated use, prefer a profile in `.room-profiles.toml`:

```bash
room play \
  --workspace . \
  --task "Discuss the next implementation slice." \
  --profile advisory-mixed
```

Profiles define participant runtime, model, role, capability scores, authority, and advisory
weight. Profiles are configuration, not fallback chains: each participant must run through its
declared runtime, or the wake cycle should fail clearly.

The default profiles map to a simple advisory loop:

- `advisory-mixed`: before work, for complex design or unclear tasks.
- `debug-recovery`: during work, when the main agent is stuck, tests fail repeatedly, or the bug is unclear.
- `final-review`: after work, before commit, push, release, or broad use; Claude Code performs the
  final review and DeepSeek provides cheap outsider risk, documentation, and usability advice.
- `cc-review`: when a stronger Claude Code review pass is useful; with `ROOM_CLAUDE_PROVIDER=deepseek`,
  Claude Code is routed to DeepSeek while the second participant uses the direct DeepSeek API on
  `deepseek-v4-flash` for a faster cheap-advisor pass.

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
