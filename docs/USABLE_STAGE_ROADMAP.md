# Usable Stage Roadmap

This document captures the next design step after the runnable CLI MVP.

The design was informed by a real `room codex-ask` wake cycle in room
`room_20260426_055525`. Two Codex participants discussed the path from a
runnable MVP to a daily-usable local workflow.

## Current State

The current MVP can:

- triage a task through `room codex-ask`
- keep simple tasks in the main Codex session
- wake two Codex agents for complex tasks
- write transcript, design, tasks, main-agent reference, execution plan, wake checkpoint, and host decision artifacts
- return machine-readable JSON for host or Codex-client integration

This is runnable, but it is not yet daily-usable. The main gap is that the output is still too close to a transcript wrapper. A usable workflow needs one concise packet that the main agent can read as reference, without making the room responsible for execution.

## Design Decision

Prioritize a simple advisory flow before adding richer orchestration:

```text
wake room -> write main-agent reference -> main agent decides/executes/verifies
```

Phase 1 should not start with participant configuration, always-on rooms, or deeper resume behavior. Those features become easier and less fragile after the reference packet contract is stable.

## Phase 0.5: Main Agent Reference Packet

Create one canonical advisory artifact for every non-trivial wake:

```text
artifacts/main_agent_reference.json
```

Implementation status: implemented. Complex wake cycles write the artifact, `room ask --json` and `room codex-ask` include it, and `room reference-context` can print it for a caller.

Rules:

- The room output is advisory only.
- The main agent remains the writer, decider, and verifier.
- A complex `room codex-ask` should return `codex_workflow.codex_action = execute_with_room_reference`.
- The main agent can still choose to ask the user or wake the room again.

## Phase 0.7: Peer Collaboration Pattern

Implementation status: implemented.

When two Codex participants use the same model/capability level, the default room behavior is `draft_review_revise`:

```text
agent A drafts
agent B reviews with concrete change requests
agent A revises
agent B final-checks
```

`parallel_opinion` remains available for cases where two independent recommendations are more useful than iterative collaboration.

Rules:

- Same-capability agents should not imply hierarchy.
- Collaboration depth should come from the action chain.
- Hierarchy is reserved for capability, cost, permission, or tool-access differences.

## Phase 1: Optional Proposal Bundle And Approval State

Create two canonical artifacts for every non-trivial wake:

```text
artifacts/room_synthesis.json
artifacts/approval_state.json
```

Implementation status: the initial contract is now implemented in the CLI MVP. Complex wake cycles write both artifacts, and `room codex-ask` includes them in the JSON response.

`room_synthesis.json` is the user-facing and host-facing proposal bundle. It should contain:

```text
room_id
source_cycle
task
problem_summary
participants
options
recommended_path
why_this_path
risks
tasks
approval_required
approval_questions
artifact_pointers
written_at
```

`approval_state.json` is the optional state machine for accepting or rejecting the proposal. In the advisory-reference alpha flow, approval starts as `not_required`; stricter integrations can require explicit acceptance before producing execution context. It should contain:

```text
room_id
synthesis_id
status              not_required | pending | accepted | rejected | superseded
actor
reason
accepted_task_ids
rejected_task_ids
created_at
updated_at
```

Rules:

- Every complex run emits exactly one current `room_synthesis.json`.
- Advisory reference execution does not require approval by default.
- `execution-context` cannot be emitted unless approval is explicitly `accepted`.
- Rejection must create a new synthesis version; it should not mutate an accepted proposal.
- The host must be able to render a concise review screen from artifacts alone, without replaying the transcript.

Acceptance criteria:

- `room codex-ask` complex path writes `room_synthesis.json` and `approval_state.json`.
- `codex_workflow.codex_action` points to `execute_with_room_reference` in the default advisory flow.
- Current tests cover `not_required`, accepted, and rejected approval states.

## Phase 1.5: Accept And Execution Context

After synthesis and approval are stable, add:

```text
room accept-plan
room reject-plan
room execution-context
```

Implementation status: the initial CLI loop is now implemented. `accept-plan` moves approval to `accepted`, `reject-plan` moves it to `rejected`, and `execution-context` refuses to emit implementation context unless approval is accepted.

`room codex-ask --room <room_id>` now recognizes accepted approval state and returns `execute_accepted_plan` with `execution_context` instead of waking a new discussion. Use `--force-wake` when a new proposal is intentionally needed.

`room accept-plan` should update `approval_state.json` and select either the full proposal or specific task ids.

`room execution-context` should emit the minimal context needed by the main Codex session to implement accepted work:

```text
room_id
synthesis_id
accepted_task_ids
implementation_brief
files_or_areas
risks
verification
artifact_pointers
```

Acceptance criteria:

- The main Codex session can continue from `execution-context` without reading the full transcript.
- Execution context is derived from an accepted synthesis, not directly from raw agent output.
- If a run is interrupted, the accepted synthesis and approval state are enough to resume.

## Phase 1.8: Read-Only Room Observer

Add a lightweight local UI so users can watch what the room discussed and inspect the resulting reference packet.

Implementation status: initial version implemented as `room serve`.

The observer is intentionally read-only:

```text
room CLI writes .room files
room serve reads .room files
browser polls /api/rooms and /api/rooms/<room_id>
```

Acceptance criteria:

- The page shows active/recent rooms.
- The page shows recent transcript turns from both Codex participants.
- The page opens `main_agent_reference.json` by default when present.
- The service can run during a wake cycle and reveal new completed turns/artifacts via polling.

## Phase 2: Recent Room Continuity

Add a smoother continuation path after approval and execution contracts exist.

Continuity should load "last usable context", not full history:

```text
task summary
latest room_synthesis
approval_state
execution result summary
unresolved questions
latest host decision
```

Candidate commands:

```text
room recent --workspace <path>
room codex-ask --continue-recent --task "<follow-up>"
```

Acceptance criteria:

- A follow-up task can reuse the latest active room without manually passing `--room`.
- The continuation prompt includes durable summaries and accepted state, not the full transcript.
- The system explains which prior room was selected and why.

## Phase 3: Participant Configuration

Move hardcoded participants into a project config after the core flow is stable.

Candidate file:

```text
.room/config.json
```

Participant profile fields:

```text
id
label
kind
model
capabilities
wake_conditions
default_prompt
max_rounds
permissions
```

Acceptance criteria:

- The default remains two Codex agents.
- A project can override participant ids, models, rounds, and wake conditions without code edits.
- The triage result explains why each configured participant was or was not activated.

## Recommended Next Implementation Slice

Public Alpha should now focus on proving the advisory loop in local use:

1. Run a real `room codex-ask` on this repository and inspect `main_agent_reference`.
2. Let the main Codex session implement one small change using the reference packet.
3. Record what was useful or noisy in the reference fields.
4. Tighten README quickstart around the advisory loop.
5. Add a tiny public demo transcript or example JSON fixture.

This keeps the project useful without requiring a long-lived room daemon or a strict execution state machine.
