# Adaptive Room Harness

Adaptive Room Harness is a local-first collaboration room for main-agent led work.

It lets a main agent open a task room, decide whether help is needed, attach participants such as agents, subagents, tools, workflows, memory systems, databases, and humans, then preserve the useful parts of the discussion as evidence, decisions, specs, reviews, cache, and reusable experience.

Short version:

> A quiet room when the task is simple, an on-demand council when the task needs more minds or tools.

## Core Idea

```text
Room = shared task context
Participant = agent | subagent | tool | workflow | memory | database | human
Mode = solo | triage | open council | pair programming | review board | SDD spec
Artifact = evidence | decision | plan | risk list | review | spec | report
Main Agent = final owner and default writer
```

This is not a fixed role-playing multi-agent demo. Researcher, Skeptic, and Reviewer are useful presets, but the core abstraction is an adaptive room with pluggable participants and explicit ownership.

## First Milestone

The first milestone is a CLI-only local MVP:

```bash
room init --workspace <path> --task "<task>"
room triage --room <room_id>
room attach --room <room_id> --kind agent --id claude_peer
room say --room <room_id> --speaker codex_main --content "..."
room add-evidence --room <room_id> --source file:...
room decide --room <room_id> --decision "..." --why "..."
room report --room <room_id>
```

The MVP should get the room data model right before building a daemon, web UI, or real multi-agent adapter orchestration.

## Design Docs

- [Idea Doc v2](docs/IDEA_DOC_V2.md)
- [Technical Architecture](docs/TECHNICAL_ARCHITECTURE.md)
- [Product Direction](docs/PRODUCT_DIRECTION.md)
