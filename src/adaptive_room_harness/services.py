from __future__ import annotations

from pathlib import Path

from adaptive_room_harness.agents import render_agent_prompt, run_codex_exec
from adaptive_room_harness.models import (
    ApprovalState,
    CollaborationPattern,
    DecisionEntry,
    EvidenceEntry,
    ExecutionContext,
    ExecutionTask,
    HostDecision,
    MainAgentReference,
    Participant,
    ParticipantKind,
    RoomState,
    RoomSynthesis,
    SynthesisOption,
    SynthesisRisk,
    SynthesisTask,
    TranscriptTurn,
    TriageResult,
    WakeCheckpoint,
    WakeExecutionPlan,
    utc_now,
)
from adaptive_room_harness.store import (
    append_decision,
    append_evidence,
    append_transcript,
    dump_json,
    list_states,
    load_participants,
    next_decision_id,
    next_evidence_id,
    next_turn_id,
    read_decisions,
    read_evidence,
    read_transcript,
    room_path,
    save_participants,
    save_state,
)

RISK_KEYWORDS = {
    "high": ["security", "auth", "production", "migration", "rollback", "compliance", "data loss"],
    "medium": ["architecture", "design", "integration", "external", "api", "database", "refactor"],
}
UNCERTAINTY_KEYWORDS = [
    "research",
    "latest",
    "unknown",
    "compare",
    "evaluate",
    "investigate",
    "why",
]

COLLABORATION_PATTERNS: set[str] = {"parallel_opinion", "draft_review_revise"}


def validate_collaboration_pattern(pattern: str) -> None:
    if pattern not in COLLABORATION_PATTERNS:
        valid = ", ".join(sorted(COLLABORATION_PATTERNS))
        raise ValueError(f"Unknown collaboration pattern: {pattern}. Valid patterns: {valid}")


def collaboration_steps(
    pattern: CollaborationPattern,
    *,
    agent_a: str,
    agent_b: str,
) -> list[dict[str, str]]:
    if pattern == "parallel_opinion":
        return [
            {
                "speaker_id": agent_a,
                "peer_id": agent_b,
                "step": "opinion",
                "instruction": (
                    "Provide an independent recommendation with concrete next steps, risks, "
                    "and acceptance criteria."
                ),
            },
            {
                "speaker_id": agent_b,
                "peer_id": agent_a,
                "step": "opinion",
                "instruction": (
                    "Provide an independent recommendation. Do not simply agree; add new "
                    "risks, alternatives, or constraints."
                ),
            },
        ]

    return [
        {
            "speaker_id": agent_a,
            "peer_id": agent_b,
            "step": "draft",
            "instruction": (
                "Write a complete first draft of the answer, design, or plan. Include "
                "specific decisions, tradeoffs, and verification ideas."
            ),
        },
        {
            "speaker_id": agent_b,
            "peer_id": agent_a,
            "step": "review",
            "instruction": (
                "Review the draft deeply. Identify concrete defects, missing assumptions, "
                "risks, and requested changes. Be specific enough that the draft can be revised."
            ),
        },
        {
            "speaker_id": agent_a,
            "peer_id": agent_b,
            "step": "revise",
            "instruction": (
                "Revise the draft using the review. Keep useful parts, fix concrete issues, "
                "and explain the main changes."
            ),
        },
        {
            "speaker_id": agent_b,
            "peer_id": agent_a,
            "step": "final_check",
            "instruction": (
                "Perform a final check of the revised result. State whether it is ready for "
                "the main agent, and list remaining risks or follow-up checks."
            ),
        },
    ]


def list_room_summaries(workspace: Path) -> list[dict[str, str | int]]:
    summaries = []
    for state in list_states(workspace):
        transcript_count = len(read_transcript(state))
        evidence_count = len(read_evidence(state))
        decision_count = len(read_decisions(state))
        summaries.append(
            {
                "room_id": state.room_id,
                "status": state.status,
                "mode": state.mode,
                "risk": state.risk_level,
                "collaboration_pattern": state.collaboration_pattern,
                "task": state.task,
                "turns": transcript_count,
                "evidence": evidence_count,
                "decisions": decision_count,
                "updated_at": state.updated_at.isoformat().replace("+00:00", "Z"),
            }
        )
    return summaries


def room_snapshot(state: RoomState) -> dict[str, object]:
    participants = load_participants(state)
    transcript = read_transcript(state)
    evidence = read_evidence(state)
    decisions = read_decisions(state)
    return {
        "state": state.model_dump(mode="json"),
        "participants": [participant.model_dump(mode="json") for participant in participants],
        "counts": {
            "participants": len(participants),
            "turns": len(transcript),
            "evidence": len(evidence),
            "decisions": len(decisions),
        },
        "recent_transcript": [
            turn.model_dump(mode="json") for turn in transcript[-5:]
        ],
        "recent_evidence": [item.model_dump(mode="json") for item in evidence[-5:]],
        "recent_decisions": [item.model_dump(mode="json") for item in decisions[-5:]],
    }


def close_room(state: RoomState, *, final_status: str = "DONE", reason: str | None = None) -> str:
    state.status = final_status
    save_state(state)
    if reason:
        record_turn(
            state,
            speaker_id=state.main_agent,
            content=reason,
            turn_type="CLOSE_REASON",
        )
    return generate_report(state)


def ensure_agent_participant(state: RoomState, participant_id: str, label: str) -> Participant:
    participants = load_participants(state)
    existing = next(
        (participant for participant in participants if participant.id == participant_id),
        None,
    )
    if existing:
        if existing.status != "active":
            existing.status = "active"
            save_participants(state, participants)
        return existing

    participant = Participant(
        id=participant_id,
        kind="agent",
        label=label,
        capabilities=["reasoning", "critique", "planning"],
        permissions=["comment"],
        status="active",
    )
    participants.append(participant)
    save_participants(state, participants)
    return participant


def play_codex_agents(
    state: RoomState,
    *,
    wake_goal: str | None = None,
    durable_context: str | None = None,
    agent_a: str = "codex_agent_a",
    agent_b: str = "codex_agent_b",
    rounds: int = 1,
    collaboration_pattern: CollaborationPattern = "draft_review_revise",
    codex_bin: str = "codex",
    model: str | None = None,
    timeout_seconds: int = 600,
) -> list[TranscriptTurn]:
    if rounds < 1:
        raise ValueError("rounds must be at least 1")
    validate_collaboration_pattern(collaboration_pattern)

    ensure_agent_participant(state, agent_a, "Codex Agent A")
    ensure_agent_participant(state, agent_b, "Codex Agent B")
    state.mode = "open_council"
    state.status = "DISCUSSION"
    state.collaboration_pattern = collaboration_pattern
    save_state(state)

    turns: list[TranscriptTurn] = []
    task_text = render_wake_task(state, wake_goal=wake_goal, durable_context=durable_context)
    for round_number in range(1, rounds + 1):
        for step in collaboration_steps(collaboration_pattern, agent_a=agent_a, agent_b=agent_b):
            prompt = render_agent_prompt(
                room_id=state.room_id,
                task=task_text,
                agent_id=step["speaker_id"],
                peer_id=step["peer_id"],
                round_number=round_number,
                collaboration_pattern=collaboration_pattern,
                collaboration_step=step["step"],
                step_instruction=step["instruction"],
                transcript_excerpt=render_transcript_excerpt(state),
            )
            result = run_codex_exec(
                codex_bin=codex_bin,
                workspace=Path(state.workspace),
                prompt=prompt,
                model=model,
                timeout_seconds=timeout_seconds,
            )
            turn = record_turn(
                state,
                speaker_id=step["speaker_id"],
                content=result.output,
                turn_type=f"AGENT_{step['step'].upper()}",
            )
            turns.append(turn)

    generate_report(state)
    return turns


def wake_room(
    state: RoomState,
    *,
    goal: str,
    agent_a: str = "codex_agent_a",
    agent_b: str = "codex_agent_b",
    rounds: int = 1,
    collaboration_pattern: CollaborationPattern = "draft_review_revise",
    codex_bin: str = "codex",
    model: str | None = None,
    timeout_seconds: int = 600,
) -> dict[str, object]:
    cycle_id = next_cycle_id(state)
    cycle_path = room_path(Path(state.workspace), state.room_id) / "cycles" / cycle_id
    cycle_path.mkdir(parents=True, exist_ok=True)

    durable_context = render_durable_context(state)
    prompt = render_wake_prompt(state, goal=goal, durable_context=durable_context)
    (cycle_path / "prompt.md").write_text(prompt)

    state.status = "WAKING"
    save_state(state)
    turns = play_codex_agents(
        state,
        wake_goal=goal,
        durable_context=durable_context,
        agent_a=agent_a,
        agent_b=agent_b,
        rounds=rounds,
        collaboration_pattern=collaboration_pattern,
        codex_bin=codex_bin,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    state.status = "OPEN_IDLE"
    save_state(state)

    artifacts = write_wake_artifacts(state, cycle_id=cycle_id, goal=goal, turns=turns)
    generate_report(state)
    return {
        "room_id": state.room_id,
        "cycle_id": cycle_id,
        "collaboration_pattern": state.collaboration_pattern,
        "turns": len(turns),
        "artifacts": {name: str(path) for name, path in artifacts.items()},
    }


def ask_room(
    state: RoomState,
    *,
    ask_text: str | None = None,
    force_wake: bool = False,
    goal: str | None = None,
    agent_a: str = "codex_agent_a",
    agent_b: str = "codex_agent_b",
    rounds: int = 1,
    collaboration_pattern: CollaborationPattern = "draft_review_revise",
    codex_bin: str = "codex",
    model: str | None = None,
    timeout_seconds: int = 600,
) -> dict[str, object]:
    triage = triage_room(state, task_text=ask_text)
    should_wake = force_wake or triage.need_activation
    result: dict[str, object] = {
        "room_id": state.room_id,
        "action": "solo",
        "triage": triage.model_dump(mode="json"),
        "wake": None,
    }
    if not should_wake:
        state.status = "OPEN_IDLE"
        save_state(state)
        generate_report(state)
        return result

    wake_goal = goal or f"Discuss and design next steps for: {ask_text or state.task}"
    wake_result = wake_room(
        state,
        goal=wake_goal,
        agent_a=agent_a,
        agent_b=agent_b,
        rounds=rounds,
        collaboration_pattern=collaboration_pattern,
        codex_bin=codex_bin,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    result["action"] = "wake"
    result["wake"] = wake_result
    return result


def build_host_decision(state: RoomState, ask_result: dict[str, object]) -> HostDecision:
    approval_state = load_approval_state(state)
    synthesis = load_room_synthesis(state)
    if approval_state and approval_state.status == "accepted":
        decision = HostDecision(
            room_id=state.room_id,
            next_step="execute",
            reason="The room synthesis has been accepted and is ready for execution.",
            recommended_action="implement",
            requires_user_approval=False,
            artifact_pointers=synthesis.artifact_pointers if synthesis else {},
            command_hint="Load execution-context and implement the accepted synthesis tasks.",
        )
        write_host_decision(state, decision)
        return decision

    if approval_state and approval_state.status == "rejected":
        decision = HostDecision(
            room_id=state.room_id,
            next_step="wake_again",
            reason="The room synthesis was rejected and needs a revised proposal.",
            recommended_action="research_more",
            requires_user_approval=True,
            artifact_pointers=synthesis.artifact_pointers if synthesis else {},
            command_hint="Run another wake cycle with the rejection reason as context.",
        )
        write_host_decision(state, decision)
        return decision

    if ask_result["action"] == "solo":
        triage = ask_result["triage"]
        reason = triage.get("solo_reason_if_no_activation") or "Triage kept this task in solo mode."
        decision = HostDecision(
            room_id=state.room_id,
            next_step="continue_solo",
            reason=reason,
            recommended_action="implement",
            requires_user_approval=False,
            command_hint="Continue in the main Codex session without waking room participants.",
        )
        write_host_decision(state, decision)
        return decision

    execution_plan = load_execution_plan(state)
    if not execution_plan:
        decision = HostDecision(
            room_id=state.room_id,
            next_step="review_only",
            reason="Wake completed but no execution_plan.json was found.",
            requires_user_approval=True,
            command_hint="Review room artifacts before continuing.",
        )
        write_host_decision(state, decision)
        return decision

    reference = load_main_agent_reference(state)
    if reference:
        next_step = "execute"
        reason = (
            "The room produced an advisory reference packet. The main agent remains the "
            "execution owner and can use it as input for the next implementation step."
        )
        command_hint = "Read main_agent_reference.json, apply main-agent judgment, then implement."
        recommended_action = "implement"
        requires_user_approval = False
    elif execution_plan.requires_user_approval or execution_plan.recommended_action == "ask_user":
        next_step = "ask_user"
        reason = "The room produced an execution plan that requires user or main-agent approval."
        command_hint = "Show the design, tasks, and execution plan to the user before editing."
        recommended_action = execution_plan.recommended_action
        requires_user_approval = execution_plan.requires_user_approval
    elif execution_plan.recommended_action == "implement":
        next_step = "execute"
        reason = "The room recommends implementation and does not require additional approval."
        command_hint = "Apply accepted tasks, then run the listed verification checks."
        recommended_action = execution_plan.recommended_action
        requires_user_approval = execution_plan.requires_user_approval
    elif execution_plan.recommended_action == "research_more":
        next_step = "wake_again"
        reason = "The room needs more research or discussion before execution."
        command_hint = "Run another wake cycle with a narrower research goal."
        recommended_action = execution_plan.recommended_action
        requires_user_approval = execution_plan.requires_user_approval
    else:
        next_step = "review_only"
        reason = "The room recommends review-only handling for this cycle."
        command_hint = "Summarize findings without changing the workspace."
        recommended_action = execution_plan.recommended_action
        requires_user_approval = execution_plan.requires_user_approval

    decision = HostDecision(
        room_id=state.room_id,
        next_step=next_step,
        reason=reason,
        recommended_action=recommended_action,
        requires_user_approval=requires_user_approval,
        artifact_pointers=execution_plan.artifact_pointers,
        command_hint=command_hint,
    )
    write_host_decision(state, decision)
    return decision


def render_transcript_excerpt(state: RoomState, limit: int = 8) -> str:
    transcript = read_transcript(state)[-limit:]
    return "\n".join(f"{turn.speaker_id}: {turn.content}" for turn in transcript)


def render_wake_task(
    state: RoomState,
    *,
    wake_goal: str | None = None,
    durable_context: str | None = None,
) -> str:
    parts = [state.task]
    if wake_goal:
        parts.extend(["", f"Current wake goal: {wake_goal}"])
    if durable_context:
        parts.extend(["", "Durable room context:", durable_context])
    return "\n".join(parts)


def render_durable_context(state: RoomState) -> str:
    artifact_dir = room_path(Path(state.workspace), state.room_id) / "artifacts"
    sections = []

    checkpoint = load_wake_checkpoint(state)
    if checkpoint:
        if checkpoint.resume_status == "authoritative":
            sections.append(
                "## wake_checkpoint.json\n\n"
                f"source_cycle: {checkpoint.source_cycle}\n"
                f"wake_goal: {checkpoint.wake_goal}\n"
                f"stable_resume:\n{render_bullets(checkpoint.stable_resume)}\n\n"
                f"pending_tasks:\n{render_bullets(checkpoint.pending_tasks)}\n\n"
                f"open_questions:\n{render_bullets(checkpoint.open_questions)}"
            )
        else:
            sections.append(
                "## wake_checkpoint.json\n\n"
                f"Checkpoint status is `{checkpoint.resume_status}`; "
                "using it as advisory context only."
            )

    names = [
        "room_summary.md",
        "design.md",
        "tasks.md",
        "main_agent_reference.json",
        "room_synthesis.json",
        "approval_state.json",
        "execution_plan.json",
        "open_questions.md",
        "decisions.md",
    ]
    for name in names:
        path = artifact_dir / name
        if path.exists() and path.read_text().strip():
            sections.append(f"## {name}\n\n{path.read_text().strip()}")
    if not sections:
        sections.append("No durable artifacts yet.")
    recent = render_transcript_excerpt(state)
    if recent:
        sections.append(f"## recent_transcript\n\n{recent}")
    return "\n\n".join(sections)


def load_wake_checkpoint(state: RoomState) -> WakeCheckpoint | None:
    path = room_path(Path(state.workspace), state.room_id) / "artifacts" / "wake_checkpoint.json"
    if not path.exists():
        return None
    return WakeCheckpoint.model_validate_json(path.read_text())


def load_execution_plan(state: RoomState) -> WakeExecutionPlan | None:
    path = room_path(Path(state.workspace), state.room_id) / "artifacts" / "execution_plan.json"
    if not path.exists():
        return None
    return WakeExecutionPlan.model_validate_json(path.read_text())


def load_room_synthesis(state: RoomState) -> RoomSynthesis | None:
    path = room_path(Path(state.workspace), state.room_id) / "artifacts" / "room_synthesis.json"
    if not path.exists():
        return None
    return RoomSynthesis.model_validate_json(path.read_text())


def load_approval_state(state: RoomState) -> ApprovalState | None:
    path = room_path(Path(state.workspace), state.room_id) / "artifacts" / "approval_state.json"
    if not path.exists():
        return None
    return ApprovalState.model_validate_json(path.read_text())


def load_main_agent_reference(state: RoomState) -> MainAgentReference | None:
    path = (
        room_path(Path(state.workspace), state.room_id)
        / "artifacts"
        / "main_agent_reference.json"
    )
    if not path.exists():
        return None
    return MainAgentReference.model_validate_json(path.read_text())


def save_approval_state(state: RoomState, approval_state: ApprovalState) -> Path:
    approval_state.updated_at = utc_now()
    path = room_path(Path(state.workspace), state.room_id) / "artifacts" / "approval_state.json"
    dump_json(path, approval_state)
    return path


def accept_plan(
    state: RoomState,
    *,
    actor: str = "codex_main",
    reason: str | None = None,
    task_ids: list[str] | None = None,
) -> ApprovalState:
    synthesis = require_room_synthesis(state)
    approval_state = require_approval_state(state)
    if approval_state.synthesis_id != synthesis.synthesis_id:
        raise ValueError("approval_state synthesis_id does not match room_synthesis")
    valid_task_ids = {task.id for task in synthesis.tasks}
    accepted_task_ids = task_ids or [task.id for task in synthesis.tasks]
    unknown_task_ids = sorted(set(accepted_task_ids) - valid_task_ids)
    if unknown_task_ids:
        raise ValueError(f"Unknown synthesis task id(s): {', '.join(unknown_task_ids)}")
    approval_state.status = "accepted"
    approval_state.actor = actor
    approval_state.reason = reason or "Accepted for execution."
    approval_state.accepted_task_ids = accepted_task_ids
    approval_state.rejected_task_ids = sorted(valid_task_ids - set(accepted_task_ids))
    save_approval_state(state, approval_state)
    record_turn(
        state,
        speaker_id=actor,
        content=f"Accepted synthesis {synthesis.synthesis_id}.",
        turn_type="APPROVAL_ACCEPTED",
    )
    return approval_state


def reject_plan(
    state: RoomState,
    *,
    actor: str = "codex_main",
    reason: str,
    task_ids: list[str] | None = None,
) -> ApprovalState:
    synthesis = require_room_synthesis(state)
    approval_state = require_approval_state(state)
    valid_task_ids = {task.id for task in synthesis.tasks}
    rejected_task_ids = task_ids or [task.id for task in synthesis.tasks]
    unknown_task_ids = sorted(set(rejected_task_ids) - valid_task_ids)
    if unknown_task_ids:
        raise ValueError(f"Unknown synthesis task id(s): {', '.join(unknown_task_ids)}")
    approval_state.status = "rejected"
    approval_state.actor = actor
    approval_state.reason = reason
    approval_state.accepted_task_ids = []
    approval_state.rejected_task_ids = rejected_task_ids
    save_approval_state(state, approval_state)
    record_turn(
        state,
        speaker_id=actor,
        content=f"Rejected synthesis {synthesis.synthesis_id}: {reason}",
        turn_type="APPROVAL_REJECTED",
    )
    return approval_state


def build_execution_context(state: RoomState) -> ExecutionContext:
    synthesis = require_room_synthesis(state)
    approval_state = require_approval_state(state)
    if approval_state.status != "accepted":
        raise ValueError("approval_state.status must be accepted before execution-context")
    accepted_task_ids = approval_state.accepted_task_ids or [task.id for task in synthesis.tasks]
    accepted_tasks = [task for task in synthesis.tasks if task.id in accepted_task_ids]
    verification = [
        acceptance
        for task in accepted_tasks
        for acceptance in task.acceptance
        if acceptance
    ]
    if not verification:
        verification = ["Run relevant project checks and record the result."]
    context = ExecutionContext(
        room_id=state.room_id,
        synthesis_id=synthesis.synthesis_id,
        accepted_task_ids=accepted_task_ids,
        implementation_brief=synthesis.recommended_path,
        risks=synthesis.risks,
        verification=verification,
        artifact_pointers={
            **synthesis.artifact_pointers,
            "room_synthesis.json": "artifacts/room_synthesis.json",
            "approval_state.json": "artifacts/approval_state.json",
            "execution_context.json": "artifacts/execution_context.json",
        },
    )
    dump_json(
        room_path(Path(state.workspace), state.room_id) / "artifacts" / "execution_context.json",
        context,
    )
    return context


def require_room_synthesis(state: RoomState) -> RoomSynthesis:
    synthesis = load_room_synthesis(state)
    if not synthesis:
        raise ValueError("room_synthesis.json not found")
    return synthesis


def require_approval_state(state: RoomState) -> ApprovalState:
    approval_state = load_approval_state(state)
    if not approval_state:
        raise ValueError("approval_state.json not found")
    return approval_state


def write_host_decision(state: RoomState, decision: HostDecision) -> Path:
    path = room_path(Path(state.workspace), state.room_id) / "artifacts" / "host_decision.json"
    dump_json(path, decision)
    return path


def render_bullets(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)


def render_wake_prompt(state: RoomState, *, goal: str, durable_context: str) -> str:
    return f"""# Wake Cycle Prompt

Room: {state.room_id}
Task: {state.task}
Goal: {goal}

## Durable Context

{durable_context}
"""


def next_cycle_id(state: RoomState) -> str:
    cycles_dir = room_path(Path(state.workspace), state.room_id) / "cycles"
    if not cycles_dir.exists():
        return "cycle_001"
    count = len(
        [path for path in cycles_dir.iterdir() if path.is_dir() and path.name.startswith("cycle_")]
    )
    return f"cycle_{count + 1:03d}"


def write_wake_artifacts(
    state: RoomState,
    *,
    cycle_id: str,
    goal: str,
    turns: list[TranscriptTurn],
) -> dict[str, Path]:
    cycle_path = room_path(Path(state.workspace), state.room_id) / "cycles" / cycle_id
    artifact_dir = room_path(Path(state.workspace), state.room_id) / "artifacts"
    transcript_lines = "\n\n".join(
        f"## {turn.speaker_id}\n\n{turn.content.strip()}" for turn in turns
    )
    summary = f"""# Room Summary

Room: {state.room_id}

Task: {state.task}

Latest wake goal: {goal}

Latest cycle: {cycle_id}

Collaboration pattern: {state.collaboration_pattern}

## Latest Discussion

{transcript_lines or "No agent turns recorded."}
"""
    design = f"""# Design

## Current Goal

{goal}

## Collaboration Pattern

{state.collaboration_pattern}

## Agent Discussion Notes

{transcript_lines or "No agent turns recorded."}
"""
    tasks = f"""# Tasks

- Review the latest wake discussion in `{cycle_id}`.
- Convert accepted recommendations into explicit decisions with `room decide`.
- Add pass/fail checks before implementation.
"""
    paths = {
        "room_summary.md": artifact_dir / "room_summary.md",
        "design.md": artifact_dir / "design.md",
        "tasks.md": artifact_dir / "tasks.md",
        "main_agent_reference.json": artifact_dir / "main_agent_reference.json",
        "room_synthesis.json": artifact_dir / "room_synthesis.json",
        "approval_state.json": artifact_dir / "approval_state.json",
        "wake_checkpoint.json": artifact_dir / "wake_checkpoint.json",
        "execution_plan.json": artifact_dir / "execution_plan.json",
        f"{cycle_id}/summary.md": cycle_path / "summary.md",
        f"{cycle_id}/design.md": cycle_path / "design.md",
        f"{cycle_id}/tasks.md": cycle_path / "tasks.md",
        f"{cycle_id}/main_agent_reference.json": cycle_path / "main_agent_reference.json",
        f"{cycle_id}/room_synthesis.json": cycle_path / "room_synthesis.json",
        f"{cycle_id}/approval_state.json": cycle_path / "approval_state.json",
        f"{cycle_id}/wake_checkpoint.json": cycle_path / "wake_checkpoint.json",
        f"{cycle_id}/execution_plan.json": cycle_path / "execution_plan.json",
    }
    checkpoint = build_wake_checkpoint(
        state,
        cycle_id=cycle_id,
        goal=goal,
        artifact_paths=paths,
        turns=turns,
    )
    execution_plan = build_execution_plan(
        state,
        cycle_id=cycle_id,
        goal=goal,
        artifact_paths=paths,
        turns=turns,
    )
    synthesis = build_room_synthesis(
        state,
        cycle_id=cycle_id,
        goal=goal,
        artifact_paths=paths,
        turns=turns,
    )
    main_agent_reference = build_main_agent_reference(
        state,
        cycle_id=cycle_id,
        goal=goal,
        artifact_paths=paths,
        synthesis=synthesis,
        execution_plan=execution_plan,
    )
    approval_state = build_approval_state(state, synthesis)
    paths["room_summary.md"].write_text(summary)
    paths["design.md"].write_text(design)
    paths["tasks.md"].write_text(tasks)
    dump_json(paths["main_agent_reference.json"], main_agent_reference)
    dump_json(paths["room_synthesis.json"], synthesis)
    dump_json(paths["approval_state.json"], approval_state)
    dump_json(paths["wake_checkpoint.json"], checkpoint)
    dump_json(paths["execution_plan.json"], execution_plan)
    paths[f"{cycle_id}/summary.md"].write_text(summary)
    paths[f"{cycle_id}/design.md"].write_text(design)
    paths[f"{cycle_id}/tasks.md"].write_text(tasks)
    dump_json(paths[f"{cycle_id}/main_agent_reference.json"], main_agent_reference)
    dump_json(paths[f"{cycle_id}/room_synthesis.json"], synthesis)
    dump_json(paths[f"{cycle_id}/approval_state.json"], approval_state)
    dump_json(paths[f"{cycle_id}/wake_checkpoint.json"], checkpoint)
    dump_json(paths[f"{cycle_id}/execution_plan.json"], execution_plan)
    return paths


def build_wake_checkpoint(
    state: RoomState,
    *,
    cycle_id: str,
    goal: str,
    artifact_paths: dict[str, Path],
    turns: list[TranscriptTurn],
) -> WakeCheckpoint:
    stable_resume = [
        f"Room task: {state.task}",
        f"Latest wake goal: {goal}",
        f"Latest cycle: {cycle_id}",
    ]
    if turns:
        stable_resume.append(
            f"Latest discussion has {len(turns)} agent turns from "
            f"{', '.join(turn.speaker_id for turn in turns)}."
        )
    return WakeCheckpoint(
        room_id=state.room_id,
        source_cycle=cycle_id,
        wake_goal=goal,
        stable_resume=stable_resume,
        pending_tasks=[
            f"Review `{cycle_id}` discussion.",
            "Convert accepted recommendations into explicit decisions.",
            "Add pass/fail checks before implementation.",
        ],
        open_questions=[
            "Which recommendations should the main agent accept?",
            "What evidence or tests are needed before implementation?",
        ],
        artifact_pointers={
            key: str(path.relative_to(room_path(Path(state.workspace), state.room_id)))
            for key, path in artifact_paths.items()
        },
    )


def build_execution_plan(
    state: RoomState,
    *,
    cycle_id: str,
    goal: str,
    artifact_paths: dict[str, Path],
    turns: list[TranscriptTurn],
) -> WakeExecutionPlan:
    return WakeExecutionPlan(
        room_id=state.room_id,
        source_cycle=cycle_id,
        summary=f"Review wake cycle {cycle_id} for goal: {goal}",
        recommended_action="implement" if turns else "review_only",
        tasks=[
            ExecutionTask(
                id="task_001",
                title=f"Review {cycle_id} design output",
                acceptance=[
                    "The main agent has read the latest design and task artifacts.",
                    "Accepted and rejected recommendations are explicit.",
                ],
                risk="low",
            ),
            ExecutionTask(
                id="task_002",
                title="Convert accepted recommendations into implementation changes",
                acceptance=[
                    "The workspace changes map back to accepted recommendations.",
                    "No participant output is applied blindly without main-agent judgment.",
                ],
                risk="medium",
            ),
            ExecutionTask(
                id="task_003",
                title="Run verification for accepted changes",
                acceptance=[
                    "Relevant lint, tests, or smoke checks have been run.",
                    "Failures are recorded before asking for another wake cycle.",
                ],
                risk="medium",
            ),
        ],
        open_questions=[
            "Which recommendations should the main agent use?",
            "Does the main agent need user approval, another wake cycle, or direct implementation?",
        ],
        requires_user_approval=False,
        artifact_pointers={
            key: str(path.relative_to(room_path(Path(state.workspace), state.room_id)))
            for key, path in artifact_paths.items()
        },
    )


def build_room_synthesis(
    state: RoomState,
    *,
    cycle_id: str,
    goal: str,
    artifact_paths: dict[str, Path],
    turns: list[TranscriptTurn],
) -> RoomSynthesis:
    participants = [turn.speaker_id for turn in turns]
    discussion_text = "\n\n".join(turn.content.strip() for turn in turns if turn.content.strip())
    recommendation_text = extract_recommendation(discussion_text) or first_nonempty_turn(turns)
    extracted_items = extract_actionable_lines(discussion_text)
    schema_items = [item for item in extracted_items if looks_like_schema_item(item)]
    rule_items = [item for item in extracted_items if looks_like_rule_item(item)]
    acceptance_items = [item for item in extracted_items if looks_like_acceptance_item(item)]
    synthesis_id = f"{cycle_id}_synthesis"
    return RoomSynthesis(
        room_id=state.room_id,
        synthesis_id=synthesis_id,
        source_cycle=cycle_id,
        task=state.task,
        problem_summary=f"Room wake goal: {goal}",
        participants=participants,
        options=[
            SynthesisOption(
                id="option_001",
                title=derive_option_title(recommendation_text),
                summary=truncate_text(recommendation_text, 900)
                or "No concrete recommendation was produced.",
                tradeoffs=build_tradeoffs(rule_items),
            )
        ],
        recommended_path=derive_recommended_path(recommendation_text, schema_items, rule_items),
        why_this_path=(
            "This path preserves the main-agent decision boundary while carrying forward concrete "
            "recommendations extracted from the participant discussion."
        ),
        risks=build_synthesis_risks(discussion_text),
        tasks=build_synthesis_tasks(schema_items, rule_items, acceptance_items),
        approval_required=False,
        approval_questions=[
            "Does the main agent want to explicitly accept this optional proposal?",
            "Should all proposal tasks be used, or only specific task ids?",
        ],
        artifact_pointers={
            key: str(path.relative_to(room_path(Path(state.workspace), state.room_id)))
            for key, path in artifact_paths.items()
        },
    )


def build_approval_state(state: RoomState, synthesis: RoomSynthesis) -> ApprovalState:
    return ApprovalState(
        room_id=state.room_id,
        synthesis_id=synthesis.synthesis_id,
        status="not_required",
        actor=state.main_agent,
        reason=(
            "Approval is optional in the advisory-reference alpha flow; "
            "the main agent remains the execution decider."
        ),
    )


def build_main_agent_reference(
    state: RoomState,
    *,
    cycle_id: str,
    goal: str,
    artifact_paths: dict[str, Path],
    synthesis: RoomSynthesis,
    execution_plan: WakeExecutionPlan,
) -> MainAgentReference:
    suggested_steps = [f"{task.id}: {task.title}" for task in synthesis.tasks]
    if not suggested_steps:
        suggested_steps = [f"{task.id}: {task.title}" for task in execution_plan.tasks]
    verification = [
        acceptance
        for task in synthesis.tasks
        for acceptance in task.acceptance
        if acceptance
    ]
    if not verification:
        verification = [
            acceptance
            for task in execution_plan.tasks
            for acceptance in task.acceptance
            if acceptance
        ]
    if not verification:
        verification = ["Run relevant project checks and record the result."]
    key_points = [synthesis.why_this_path]
    key_points.extend(option.summary for option in synthesis.options[:2] if option.summary)
    return MainAgentReference(
        room_id=state.room_id,
        reference_id=f"{cycle_id}_main_agent_reference",
        source_cycle=cycle_id,
        task=state.task,
        objective=goal,
        confidence="medium",
        recommended_focus=synthesis.recommended_path,
        key_points=[
            f"Collaboration pattern: {state.collaboration_pattern}",
            *[truncate_text(item, 500) for item in key_points if item],
        ],
        suggested_steps=suggested_steps,
        risks=[risk.summary for risk in synthesis.risks],
        verification=verification,
        artifact_pointers={
            key: str(path.relative_to(room_path(Path(state.workspace), state.room_id)))
            for key, path in artifact_paths.items()
        },
    )


def first_nonempty_turn(turns: list[TranscriptTurn]) -> str:
    for turn in turns:
        content = turn.content.strip()
        if content:
            return content
    return ""


def extract_recommendation(text: str) -> str:
    markers = [
        "Decision recommendation",
        "decision recommendation",
        "Recommendation",
        "recommendation",
    ]
    for marker in markers:
        index = text.find(marker)
        if index >= 0:
            excerpt = text[index:]
            lines = [line.strip("` ").strip() for line in excerpt.splitlines() if line.strip()]
            useful = [line for line in lines if not line.lower().startswith(marker.lower())]
            return " ".join(useful[:4]).strip()
    return ""


def extract_actionable_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cleaned = line.strip("-*` ").strip()
        if not cleaned or cleaned.startswith("{") or cleaned.startswith("}"):
            continue
        if is_actionable_line(cleaned):
            lines.append(cleaned)
    return dedupe_preserve_order(lines)


def is_actionable_line(line: str) -> bool:
    lower = line.lower()
    prefixes = (
        "schema",
        "rule",
        "rules",
        "acceptance",
        "lifecycle",
        "command",
        "status",
    )
    contains = (
        "should",
        "must",
        "require",
        "validates",
        "fails",
        "idempotent",
        "conflict",
        "execution_id",
        "source_context",
        "status",
        "schema",
        "acceptance criteria",
        "downstream",
        "reconstruct",
    )
    return lower.startswith(prefixes) or any(token in lower for token in contains)


def looks_like_schema_item(line: str) -> bool:
    lower = line.lower()
    return any(
        token in lower
        for token in [
            "execution_id",
            "schema_version",
            "participant",
            "summary",
            "outputs",
            "artifacts",
            "source_context",
            "idempotency_key",
            "started_at",
            "finished_at",
        ]
    )


def looks_like_rule_item(line: str) -> bool:
    lower = line.lower()
    return any(
        token in lower
        for token in [
            "validates",
            "idempotent",
            "conflict",
            "only",
            "open",
            "closed",
            "stale",
            "source_context",
            "direct",
        ]
    )


def looks_like_acceptance_item(line: str) -> bool:
    lower = line.lower()
    return any(
        token in lower
        for token in ["acceptance", "fails", "must", "downstream", "detect", "reconstruct"]
    )


def derive_option_title(recommendation: str) -> str:
    if "finish-execution" in recommendation or "execution_result" in recommendation:
        return "Use finish-execution as the single execution result writer"
    if recommendation:
        return truncate_text(recommendation, 80)
    return "Proceed with the synthesized room recommendation"


def build_tradeoffs(rule_items: list[str]) -> list[str]:
    tradeoffs = [truncate_text(item, 180) for item in rule_items[:3]]
    if len(tradeoffs) < 2:
        tradeoffs.extend(
            [
                "Keeps execution completion explicit and auditable.",
                "Requires approval before workspace edits continue.",
            ][: 2 - len(tradeoffs)]
        )
    return tradeoffs


def derive_recommended_path(
    recommendation: str,
    schema_items: list[str],
    rule_items: list[str],
) -> str:
    details = []
    if recommendation:
        details.append(truncate_text(recommendation, 700))
    if schema_items:
        schema_focus = "; ".join(truncate_text(item, 120) for item in schema_items[:4])
        details.append("Schema focus: " + schema_focus)
    if rule_items:
        details.append("Rules: " + "; ".join(truncate_text(item, 120) for item in rule_items[:3]))
    if details:
        return " ".join(details)
    return "Review and approve the synthesized proposal before implementation."


def build_synthesis_risks(text: str) -> list[SynthesisRisk]:
    risks: list[SynthesisRisk] = []
    for line in extract_actionable_lines(text):
        lower = line.lower()
        if "risk" in lower or "conflict" in lower or "stale" in lower or "overwrite" in lower:
            risks.append(
                SynthesisRisk(
                    id=f"risk_{len(risks) + 1:03d}",
                    summary=truncate_text(line, 220),
                    mitigation=(
                        "Validate the execution context and enforce approval/idempotency rules."
                    ),
                    level="medium",
                )
            )
    if not risks:
        risks.append(
            SynthesisRisk(
                id="risk_001",
                summary="Agent discussion may contain useful but unverified recommendations.",
                mitigation="Require approval and verification before implementation.",
                level="medium",
            )
        )
    return risks[:4]


def build_synthesis_tasks(
    schema_items: list[str],
    rule_items: list[str],
    acceptance_items: list[str],
) -> list[SynthesisTask]:
    tasks = [
        SynthesisTask(
            id="task_001",
            title="Define the structured proposal schema",
            acceptance=schema_items[:6] or ["The schema fields are explicit and documented."],
            risk="medium",
        ),
        SynthesisTask(
            id="task_002",
            title="Implement the lifecycle and validation rules",
            acceptance=rule_items[:6]
            or ["The command validates state transitions before writing artifacts."],
            risk="medium",
        ),
        SynthesisTask(
            id="task_003",
            title="Verify accepted behavior and downstream readability",
            acceptance=acceptance_items[:6]
            or [
                "Relevant checks pass or failures are captured.",
                "A downstream reader can reconstruct the result from room artifacts.",
            ],
            risk="medium",
        ),
    ]
    return tasks


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    unique = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def triage_room(state: RoomState, task_text: str | None = None) -> TriageResult:
    raw_task = task_text or state.task
    task = raw_task.lower()
    high_risk = any(keyword in task for keyword in RISK_KEYWORDS["high"])
    medium_risk = any(keyword in task for keyword in RISK_KEYWORDS["medium"])
    uncertain = any(keyword in task for keyword in UNCERTAINTY_KEYWORDS)

    if high_risk:
        risk_level = "high"
    elif medium_risk or len(task) > 180:
        risk_level = "medium"
    else:
        risk_level = "low"

    uncertainty_level = "medium" if uncertain else "low"
    need_activation = risk_level != "low" or uncertain

    suggested = []
    if uncertain or "latest" in task or "research" in task:
        suggested.append(
            {"id": "websearch", "reason": "The task appears to need external or current facts."}
        )
    if risk_level in {"medium", "high"}:
        suggested.append(
            {"id": "review_board", "reason": "The task has enough risk to justify critique."}
        )
    if "spec" in task or "design" in task or risk_level == "high":
        suggested.append({"id": "sdd", "reason": "A durable spec/checkpoint may reduce ambiguity."})

    recommended_mode = (
        "research_sprint" if any(item["id"] == "websearch" for item in suggested) else "solo"
    )
    if risk_level == "high":
        recommended_mode = "review_board"
    elif risk_level == "medium" and not suggested:
        recommended_mode = "open_council"

    result = TriageResult(
        need_activation=need_activation,
        risk_level=risk_level,
        uncertainty_level=uncertainty_level,
        recommended_mode=recommended_mode,
        suggested_participants=suggested,
        solo_reason_if_no_activation=(
            "Small local task with clear success criteria and no obvious external dependency."
            if not need_activation
            else None
        ),
    )
    state.mode = result.recommended_mode
    state.risk_level = result.risk_level
    save_state(state)
    write_artifact(
        state,
        "triage_result.md",
        render_triage_markdown(state, result),
    )
    return result


def attach_participant(
    state: RoomState,
    *,
    participant_id: str,
    kind: ParticipantKind,
    label: str | None = None,
    capabilities: list[str] | None = None,
    permissions: list[str] | None = None,
    status: str | None = None,
    cost_tier: str | None = None,
) -> Participant:
    participants = load_participants(state)
    if any(participant.id == participant_id for participant in participants):
        raise ValueError(f"Participant already exists: {participant_id}")
    participant = Participant(
        id=participant_id,
        kind=kind,
        label=label,
        capabilities=capabilities or [],
        permissions=permissions or ["comment"],
        status=status or ("sleeping" if kind in {"agent", "subagent"} else "available"),
        cost_tier=cost_tier,
    )
    participants.append(participant)
    save_participants(state, participants)
    return participant


def record_turn(
    state: RoomState,
    *,
    speaker_id: str,
    content: str,
    turn_type: str = "MESSAGE",
    evidence: list[str] | None = None,
    confidence: float | None = None,
) -> TranscriptTurn:
    participant = next(
        (item for item in load_participants(state) if item.id == speaker_id),
        None,
    )
    turn = TranscriptTurn(
        room_id=state.room_id,
        turn_id=next_turn_id(state),
        speaker_id=speaker_id,
        speaker_kind=participant.kind if participant else "agent",
        type=turn_type,
        content=content,
        evidence=evidence or [],
        confidence=confidence,
    )
    append_transcript(state, turn)
    return turn


def record_evidence(
    state: RoomState,
    *,
    source: str,
    summary: str | None = None,
    content: str | None = None,
    added_by: str = "codex_main",
) -> EvidenceEntry:
    evidence = EvidenceEntry(
        room_id=state.room_id,
        evidence_id=next_evidence_id(state),
        source=source,
        summary=summary,
        content=content,
        added_by=added_by,
    )
    append_evidence(state, evidence)
    return evidence


def record_decision(
    state: RoomState,
    *,
    decision: str,
    why: str,
    owner: str = "codex_main",
    alternatives_rejected: list[str] | None = None,
    accepted_risks: list[str] | None = None,
) -> DecisionEntry:
    entry = DecisionEntry(
        room_id=state.room_id,
        decision_id=next_decision_id(state),
        owner=owner,
        decision=decision,
        why=why,
        alternatives_rejected=alternatives_rejected or [],
        accepted_risks=accepted_risks or [],
    )
    append_decision(state, entry)
    return entry


def write_artifact(state: RoomState, name: str, content: str) -> Path:
    if "/" in name or name.startswith("."):
        raise ValueError("Artifact name must be a simple filename")
    path = room_path(Path(state.workspace), state.room_id) / "artifacts" / name
    path.write_text(content)
    return path


def generate_report(state: RoomState) -> str:
    participants = load_participants(state)
    transcript = read_transcript(state)
    evidence = read_evidence(state)
    decisions = read_decisions(state)
    reference = load_main_agent_reference(state)

    lines = [
        f"# Room Report: {state.room_id}",
        "",
        f"- Workspace: `{state.workspace}`",
        f"- Task: {state.task}",
        f"- Status: {state.status}",
        f"- Mode: {state.mode}",
        f"- Risk: {state.risk_level}",
        f"- Collaboration pattern: {state.collaboration_pattern}",
        f"- Generated: {utc_now().isoformat().replace('+00:00', 'Z')}",
        "",
        "## Participants",
        "",
    ]
    lines.extend(
        f"- `{participant.id}` ({participant.kind}, {participant.status})"
        for participant in participants
    )
    lines.extend(["", "## Evidence", ""])
    lines.extend(
        f"- `{item.evidence_id}` {item.source}" + (f" - {item.summary}" if item.summary else "")
        for item in evidence
    )
    if not evidence:
        lines.append("- None recorded.")
    lines.extend(["", "## Decisions", ""])
    lines.extend(f"- `{item.decision_id}` {item.decision} Why: {item.why}" for item in decisions)
    if not decisions:
        lines.append("- None recorded.")
    lines.extend(["", "## Main Agent Reference", ""])
    if reference:
        lines.extend(
            [
                f"- Reference: `{reference.reference_id}`",
                f"- Source cycle: `{reference.source_cycle}`",
                f"- Advisory only: `{str(reference.advisory_only).lower()}`",
                f"- Recommended focus: {reference.recommended_focus}",
            ]
        )
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Recent Transcript", ""])
    lines.extend(
        f"- `{turn.turn_id}` {turn.speaker_id}: {turn.content}" for turn in transcript[-8:]
    )
    if not transcript:
        lines.append("- None recorded.")
    lines.append("")
    report = "\n".join(lines)
    report_path = room_path(Path(state.workspace), state.room_id) / "reports" / "final.md"
    report_path.write_text(report)
    return report


def render_triage_markdown(state: RoomState, result: TriageResult) -> str:
    lines = [
        f"# Triage Result: {state.room_id}",
        "",
        f"- Need activation: `{str(result.need_activation).lower()}`",
        f"- Risk level: `{result.risk_level}`",
        f"- Uncertainty level: `{result.uncertainty_level}`",
        f"- Recommended mode: `{result.recommended_mode}`",
    ]
    if result.solo_reason_if_no_activation:
        lines.append(f"- Solo reason: {result.solo_reason_if_no_activation}")
    lines.extend(["", "## Suggested Participants", ""])
    if result.suggested_participants:
        lines.extend(f"- `{item.id}`: {item.reason}" for item in result.suggested_participants)
    else:
        lines.append("- None.")
    lines.append("")
    return "\n".join(lines)
