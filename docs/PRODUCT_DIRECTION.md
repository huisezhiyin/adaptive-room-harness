# Product Direction

## Positioning

Adaptive Room Harness is a local-first collaboration room for a main agent.

The main agent remains the task owner, final decider, and default writer. Other participants help by discussing, researching, reviewing, challenging assumptions, running bounded tools, querying external context, or converting stable conclusions into durable artifacts.

## Why It Exists

Modern coding agents are strong enough to execute, but complex work still benefits from:

- independent critique
- fresh external facts
- project memory
- workflow discipline
- review and validation
- explicit decisions
- reusable artifacts

The system should preserve the user's natural way of working with an agent: open discussion first, structure when useful.

## Non-Goals

- Do not build a general multi-agent platform first.
- Do not require fixed roles for every task.
- Do not let multiple agents write directly into the same workspace by default.
- Do not create unbounded autonomous loops.
- Do not replace expcap, SDD, MCP, A2A, or host-native subagents.

## Operating Principle

The room should often decide not to activate anyone.

Simple tasks should stay quiet and let the main agent proceed. Complex, risky, uncertain, or evidence-heavy tasks can wake selected participants.

When participants have the same capability level, collaboration should be deep and peer-shaped rather than hierarchical. The default should look like draft, review, revise, and final check. Hierarchy only becomes the right abstraction when participants differ in model strength, cost, permissions, or tool access.

## Integration Principle

Adaptive Room Harness governs live collaboration.

Other systems remain specialized:

- expcap stores reusable project and team experience.
- SDD turns stable discussion into specs, checkpoints, and tasks.
- MCP connects external tools and resources.
- Host agents keep their native subagent and skill systems.
