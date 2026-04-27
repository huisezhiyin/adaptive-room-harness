# Technical Architecture

## Stack Decision

Start with Python.

Reasons:

- fastest path to a local CLI MVP
- simple filesystem and SQLite operations
- easy integration with existing local CLIs such as expcap
- good fit for JSONL transcripts and structured local artifacts
- enough flexibility to add HTTP/WebSocket service later

Initial stack:

```text
Python 3.11+
Typer        CLI framework
Pydantic v2  typed data contracts
Rich         readable terminal output
SQLite       local index and query layer
JSONL        append-only transcript and event logs
pytest       tests
ruff         lint and formatting
```

Packaging:

```text
pyproject.toml
src/adaptive_room_harness/
console script: room
```

## Architecture Shape

```text
Main Agent / User
  ↓
room CLI
  ↓
Application Services
  ├─ Room Service
  ├─ Triage Service
  ├─ Participant Registry
  ├─ Transcript Service
  ├─ Evidence Service
  ├─ Decision Service
  └─ Report Service
  ↓
Local Store
  ├─ filesystem artifacts
  ├─ JSONL event logs
  └─ SQLite index
  ↓
Adapters
  ├─ expcap memory adapter
  ├─ SDD workflow adapter
  ├─ shell/tool adapter
  ├─ web/search adapter
  └─ agent adapters
```

## Core Domain Objects

### Room

A task-scoped collaboration space.

Fields:

```text
room_id
workspace
task
status
mode
main_agent
risk_level
created_at
updated_at
```

### Participant

Anything that can contribute to the room.

Kinds:

```text
agent
subagent
tool
workflow
memory
database
human
```

Capabilities:

```text
reasoning
coding
review
critique
research
web_search
doc_read
db_query
vector_retrieval
test_run
spec_write
memory_recall
memory_capture
summary
security_check
```

### Mode

How the room collaborates.

Initial modes:

```text
solo
triage
open_council
role_bounded
pair_programming
red_team
review_board
research_sprint
sdd_spec
execution_support
```

### Artifact

Durable output from the room.

Examples:

```text
evidence bundle
decision brief
implementation plan
risk list
test plan
review findings
SDD spec
patch proposal
final report
expcap candidate
room summary
```

## Local Data Layout

The MVP uses a local-first room directory:

```text
.room/
  rooms/
    room_20260425_001/
      goal.md
      state.json
      participants.json
      permissions.json
      modes.json
      transcript.jsonl
      evidence.jsonl
      decisions.jsonl
      artifacts/
        room_summary.md
        wake_checkpoint.json
        main_agent_reference.json
        room_synthesis.json
        approval_state.json
        execution_plan.json
        host_decision.json
        design.md
        tasks.md
        implementation_plan.md
        risk_list.md
        review_findings.md
      cycles/
        cycle_001/
          prompt.md
          summary.md
          wake_checkpoint.json
          main_agent_reference.json
          room_synthesis.json
          approval_state.json
          execution_plan.json
          design.md
          tasks.md
      reports/
        final.md
      cache/
        working_context.json
        expcap_context.json
      sdd/
        requirements.md
        design.md
        tasks.md
      patches/
```

SQLite can be added as a secondary index once the file contract is stable.

## Room Lifecycle

Long-running work should keep one durable room and wake participants only when useful.

```text
OPEN_IDLE -> WAKING -> DISCUSSING -> CAPTURING -> OPEN_IDLE -> CLOSED
```

The room is the durable memory boundary. Agent processes are not long-lived by default. Each wake cycle starts fresh participant invocations through the configured runtime adapters and gives them:

- `wake_checkpoint.json` when present and authoritative
- durable artifacts such as `room_summary.md`, `design.md`, and `tasks.md`
- recent transcript turns
- the current wake goal

Full transcript history remains available for audit and retrieval, but should not be injected into every prompt.

## Collaboration Patterns

When participants have roughly equal model capability, the default is peer collaboration, not hierarchy.

The default pattern is:

```text
draft_review_revise
```

It runs one collaboration round as:

```text
participant_a  draft        produce a complete first draft
participant_b  review       critique the draft with concrete requested changes
participant_a  revise       revise using the review
participant_b  final_check  check whether the revised result is ready
```

This makes the transcript show real interaction between equally capable participants. Use `parallel_opinion` when the desired behavior is two independent recommendations instead:

```text
participant_a  opinion
participant_b  opinion
```

## Runtime Neutrality

The room orchestrates participants, not a single vendor or CLI. A participant can be backed by any supported runtime adapter, currently including `codex-cli`, `claude-cli`, and `anthropic-api`.

Requested runtime is authoritative for a wake cycle. Once a profile or command resolves a participant to a runtime, that participant either runs through that runtime or fails with a visible runtime/configuration error. The harness must not silently reroute a failed `claude-cli` or `anthropic-api` participant to `codex-cli`.

Fallbacks may become useful later, but they must be explicit profile policy and recorded in room artifacts. Hidden fallback would make transcripts misleading because the recorded participant would not match the agent that actually spoke.

Layered hierarchy should be reserved for cases where participants differ in model capability, cost, permissions, or access to tools.

`wake_checkpoint.json` is the authoritative resume artifact for the next wake cycle. It contains:

```text
resume_status       authoritative | partial | stale
source_cycle        cycle that wrote the checkpoint
wake_goal           latest wake goal
stable_resume       accepted durable context for automatic resume
pending_tasks       work that still needs main-agent decision or execution
open_questions      unresolved questions
artifact_pointers   relative paths to summary/design/tasks/cycle files
```

If the checkpoint is not `authoritative`, it can be included as advisory context, but automatic resume should fall back to durable artifacts and recent transcript.

`main_agent_reference.json` is the primary Public Alpha handoff artifact for the current wake cycle. It is advisory only: the room does not write workspace changes and does not own execution. The main agent reads this packet, applies judgment, implements the chosen work, and verifies the result. It contains:

```text
schema_version
room_id
reference_id
source_cycle
task
objective
advisory_only
confidence
recommended_focus
key_points
suggested_steps
risks
verification
artifact_pointers
written_at
```

`room reference-context` prints this artifact for a host or main agent. `room codex-ask` includes it directly in the JSON response, and for the normal complex-task path returns `codex_workflow.codex_action = execute_with_room_reference`.

`room serve` is a read-only observer for this local file contract. It starts a small standard-library HTTP server and serves:

```text
/                         browser UI
/api/rooms                room list and compact status
/api/rooms/<room_id>      room snapshot, recent transcript, and artifacts
```

The first version uses browser polling instead of token streaming. This keeps the service simple and reliable while still making each completed agent turn and artifact update visible within a couple of seconds.

`room_synthesis.json` is supplemental review metadata for the current wake cycle. In the Public Alpha, `main_agent_reference.json` is the canonical handoff artifact and the main agent remains the execution decider. The synthesis object is still useful when a caller wants to render a fuller proposal or explicitly accept/reject a plan. It contains:

```text
synthesis_id        stable id for this proposal
source_cycle        cycle that produced the synthesis
problem_summary     concise task framing
participants        contributors used for the proposal
options             considered options and tradeoffs
recommended_path    proposed path forward
why_this_path       rationale for the recommendation
risks               risk list with mitigations
tasks               proposed tasks with acceptance checks
approval_required   whether this proposal must be explicitly accepted before use
approval_questions  questions to answer before acceptance
artifact_pointers   relative room artifact paths
```

`approval_state.json` is the optional proposal approval state machine. In the default advisory-reference flow it starts as `not_required`; stricter integrations can move it through explicit accept/reject commands:

```text
synthesis_id        proposal being approved
status              not_required | pending | accepted | rejected | superseded
actor               user or agent that set the current state
reason              optional approval or rejection reason
accepted_task_ids   selected tasks when partially accepted
rejected_task_ids   rejected tasks when partially accepted
created_at
updated_at
```

`execution_plan.json` is the host-facing handoff artifact for the current wake cycle. It contains:

```text
source_cycle              cycle that wrote the plan
summary                   short execution-oriented wake summary
recommended_action        implement | ask_user | research_more | review_only
tasks                     concrete task stubs with acceptance checks and risk
open_questions            questions the host or user should resolve
requires_user_approval    whether the host should pause before implementation
artifact_pointers         relative paths to summary/design/tasks/checkpoint files
```

The Public Alpha defaults to `recommended_action = implement` and `requires_user_approval = false` after a successful agent discussion. This does not mean the room owns execution; it means the main agent can use the advisory reference immediately, while still choosing to ask the user, explicitly accept a plan, or wake the room again.

`host_decision.json` is the Codex-client routing artifact. It is produced by `room host-ask` after triage or wake:

```text
next_step                 continue_solo | ask_user | execute | wake_again | review_only
reason                    why the host should take that step
recommended_action        copied from execution_plan when present
requires_user_approval    whether the host should pause before edits
artifact_pointers         relative room artifact paths
command_hint              short operational hint for the host
```

`room codex-ask` adds a volatile `codex_workflow` object to the JSON response. It is intentionally not a durable room artifact; it is an instruction packet for the current main Codex session:

```text
codex_action       continue_main_session | present_room_output_for_approval |
                   execute_accepted_plan | wake_room_again | summarize_review_only
instruction        direct instruction for the main Codex session
user_message       short user-facing explanation
```

`room execution-context` writes `artifacts/execution_context.json` only after `approval_state.status` is `accepted`. It contains:

```text
room_id
synthesis_id
accepted_task_ids
implementation_brief
risks
verification
artifact_pointers
```

When `room codex-ask --room <room_id>` sees an accepted approval state, it short-circuits normal triage and returns:

```text
action                         accepted
host_decision.next_step         execute
codex_workflow.codex_action     execute_accepted_plan
execution_context               accepted implementation context
```

Passing `--force-wake` bypasses this short-circuit and starts a new discussion cycle.

This keeps the MVP local-first, debuggable, and cost-controlled while still supporting one room across multiple phases of a larger task.

## CLI MVP

Initial commands:

```text
room init
room triage
room attach
room say
room ask
room host-ask
room codex-ask
room accept-plan
room reject-plan
room execution-context
room reference-context
room serve
room play
room wake
room add-evidence
room decide
room artifact
room report
```

`room ask` is the main task entry point for the MVP. It runs local triage first:

```text
simple / low-risk       -> solo recommendation, no agent wake
complex / uncertain     -> wake cycle with configured participants
force wake              -> wake regardless of triage
```

The first implementation used Codex CLI as the initial agent adapter. The room contract is runtime-neutral and now supports multiple adapters.

`room ask --json` is the intended integration surface for a host agent. It returns machine-readable action, triage, wake metadata, artifact paths, captured design/tasks content, `main_agent_reference`, `room_synthesis`, `approval_state`, and `execution_plan` so the host can decide whether to execute, ask the user for approval, or run another wake cycle.

`room host-ask` is the narrower Codex-client entry point. It returns the same room result plus `host_decision`, and writes `artifacts/host_decision.json` for durable resume.

`room codex-ask` is the preferred current client workflow entry point. The caller should inspect `codex_workflow.codex_action`:

```text
continue_main_session              continue without waking agents
present_room_output_for_approval   show room_synthesis/approval_state and wait
execute_with_room_reference        use advisory room output as main-agent input
execute_accepted_plan              implement accepted tasks and verify
wake_room_again                    run another wake cycle
summarize_review_only              summarize without workspace edits
```

## Permission Model

Default:

```text
Main Agent is the only workspace writer and final decider.
```

Permissions:

```text
observe
comment
read_workspace
search_network
query_db
run_command
write_artifact
propose_patch
write_workspace
decide
admin
```

Non-main participants can propose patches or write room artifacts, but should not directly mutate the workspace unless explicitly elevated.

## Integration Plan

Phase 1:

- filesystem room contract
- JSONL transcript/evidence/decision logs
- final report generation
- Codex CLI two-agent wake cycle
- durable summary/design/tasks artifacts
- expcap context import/export placeholders
- SDD artifact folders

Phase 2:

- SQLite index
- expcap CLI integration
- simple shell/tool adapters
- preset modes

Phase 3:

- agent adapters
- host-native subagent support
- HTTP/WebSocket room server
- optional web observer UI
