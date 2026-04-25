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
        implementation_plan.md
        risk_list.md
        review_findings.md
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

## CLI MVP

Initial commands:

```text
room init
room triage
room attach
room say
room ask
room add-evidence
room decide
room artifact
room report
```

The first implementation should not need real external model adapters. Manual and local-only commands are enough to validate the contract.

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

