from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.json import JSON
from rich.table import Table

from adaptive_room_harness.models import ParticipantKind
from adaptive_room_harness.server import serve_observer
from adaptive_room_harness.services import (
    accept_plan,
    ask_room,
    attach_participant,
    build_execution_context,
    build_host_decision,
    close_room,
    generate_report,
    list_room_summaries,
    load_approval_state,
    load_main_agent_reference,
    play_codex_agents,
    record_decision,
    record_evidence,
    record_turn,
    reject_plan,
    room_snapshot,
    triage_room,
    wake_room,
    write_artifact,
)
from adaptive_room_harness.store import create_room, load_state, room_path

app = typer.Typer(
    name="room",
    help="Adaptive Room Harness CLI.",
    no_args_is_help=True,
)
console = Console(width=160)


def room_state(workspace: Path, room_id: str):
    try:
        return load_state(workspace, room_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(f"Room not found: {room_id}") from exc


@app.command()
def version() -> None:
    """Show the installed version."""
    from adaptive_room_harness import __version__

    console.print(__version__)


@app.command()
def init(
    workspace: Annotated[Path, typer.Option(help="Workspace path for the room.")],
    task: Annotated[str, typer.Option(help="Task summary for the room.")],
) -> None:
    """Create a local task room."""

    state = create_room(workspace, task)
    console.print(f"[bold green]Created room[/bold green] {state.room_id}")
    console.print(f"path: {room_path(Path(state.workspace), state.room_id)}")


@app.command("list")
def list_rooms(
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
) -> None:
    """List local task rooms."""

    summaries = list_room_summaries(workspace)
    if not summaries:
        console.print("No rooms found.")
        return

    table = Table()
    table.add_column("Room", no_wrap=True, overflow="fold")
    table.add_column("Status")
    table.add_column("Mode")
    table.add_column("Pattern")
    table.add_column("Risk")
    table.add_column("Turns")
    table.add_column("Evidence")
    table.add_column("Decisions")
    table.add_column("Task")
    for summary in summaries:
        table.add_row(
            str(summary["room_id"]),
            str(summary["status"]),
            str(summary["mode"]),
            str(summary["collaboration_pattern"]),
            str(summary["risk"]),
            str(summary["turns"]),
            str(summary["evidence"]),
            str(summary["decisions"]),
            str(summary["task"]),
        )
    console.print(table)


@app.command()
def show(
    room: Annotated[str, typer.Option(help="Room id.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
) -> None:
    """Show a room snapshot as JSON."""

    state = room_state(workspace, room)
    console.print(JSON.from_data(room_snapshot(state)))


@app.command()
def status(
    room: Annotated[str, typer.Option(help="Room id.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
) -> None:
    """Show a compact room status."""

    state = room_state(workspace, room)
    snapshot = room_snapshot(state)
    counts = snapshot["counts"]
    table = Table("Field", "Value")
    table.add_row("room", state.room_id)
    table.add_row("task", state.task)
    table.add_row("status", state.status)
    table.add_row("mode", state.mode)
    table.add_row("collaboration_pattern", state.collaboration_pattern)
    table.add_row("risk", state.risk_level)
    table.add_row("participants", str(counts["participants"]))
    table.add_row("turns", str(counts["turns"]))
    table.add_row("evidence", str(counts["evidence"]))
    table.add_row("decisions", str(counts["decisions"]))
    console.print(table)


@app.command()
def triage(
    room: Annotated[str, typer.Option(help="Room id.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
) -> None:
    """Triage whether a room should activate more participants."""

    state = room_state(workspace, room)
    result = triage_room(state)
    console.print(JSON(result.model_dump_json(indent=2)))


@app.command()
def ask(
    task: Annotated[str, typer.Option(help="Task summary.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    room: Annotated[str | None, typer.Option(help="Existing room id.")] = None,
    goal: Annotated[str | None, typer.Option(help="Wake-cycle goal override.")] = None,
    force_wake: Annotated[
        bool, typer.Option(help="Wake participants even if triage says solo.")
    ] = False,
    rounds: Annotated[int, typer.Option(help="Number of two-agent rounds when waking.")] = 1,
    collaboration_pattern: Annotated[
        str,
        typer.Option(help="Agent collaboration pattern: draft_review_revise or parallel_opinion."),
    ] = "draft_review_revise",
    agent_a: Annotated[str, typer.Option(help="First Codex participant id.")] = "codex_agent_a",
    agent_b: Annotated[str, typer.Option(help="Second Codex participant id.")] = "codex_agent_b",
    codex_bin: Annotated[str, typer.Option(help="Codex CLI executable.")] = "codex",
    model: Annotated[
        str | None,
        typer.Option(help="Codex model override. Defaults to ROOM_CODEX_MODEL or gpt-5.4."),
    ] = None,
    timeout_seconds: Annotated[int, typer.Option(help="Timeout per agent invocation.")] = 600,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON.")
    ] = False,
) -> None:
    """Triage a task and wake participants only when useful."""

    state = room_state(workspace, room) if room else create_room(workspace, task)
    if room and task != state.task:
        record_turn(
            state,
            speaker_id=state.main_agent,
            content=f"New ask: {task}",
            turn_type="ASK",
        )

    try:
        result = ask_room(
            state,
            ask_text=task,
            force_wake=force_wake,
            goal=goal,
            agent_a=agent_a,
            agent_b=agent_b,
            rounds=rounds,
            collaboration_pattern=collaboration_pattern,
            codex_bin=codex_bin,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    payload = render_ask_payload(state, result)
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return

    console.print(f"room: {state.room_id}")
    console.print(f"action: {result['action']}")
    if result["action"] == "solo":
        triage = result["triage"]
        console.print(f"mode: {triage['recommended_mode']}")
        console.print(f"reason: {triage['solo_reason_if_no_activation']}")
        return

    wake_result = result["wake"]
    console.print(f"cycle: {wake_result['cycle_id']}")
    console.print(f"design: {wake_result['artifacts']['design.md']}")
    console.print(f"tasks: {wake_result['artifacts']['tasks.md']}")
    console.print(f"reference: {wake_result['artifacts']['main_agent_reference.json']}")
    console.print(f"execution_plan: {wake_result['artifacts']['execution_plan.json']}")
    execution_plan = payload["execution_plan"]
    console.print(f"recommended_action: {execution_plan['recommended_action']}")
    console.print(f"requires_user_approval: {execution_plan['requires_user_approval']}")
    console.print()
    console.rule("Design")
    console.print(read_text_preview(Path(wake_result["artifacts"]["design.md"])))
    console.rule("Tasks")
    console.print(read_text_preview(Path(wake_result["artifacts"]["tasks.md"])))


def render_ask_payload(state, result: dict[str, object]) -> dict[str, object]:
    payload: dict[str, object] = {
        "room_id": state.room_id,
        "action": result["action"],
        "triage": result["triage"],
    }
    if result["action"] == "solo":
        return payload

    wake_result = result["wake"]
    artifacts = wake_result["artifacts"]
    design_path = Path(artifacts["design.md"])
    tasks_path = Path(artifacts["tasks.md"])
    reference_path = Path(artifacts["main_agent_reference.json"])
    execution_plan_path = Path(artifacts["execution_plan.json"])
    synthesis_path = Path(artifacts["room_synthesis.json"])
    approval_state_path = Path(artifacts["approval_state.json"])
    payload["wake"] = wake_result
    payload["design"] = design_path.read_text()
    payload["tasks"] = tasks_path.read_text()
    payload["main_agent_reference"] = json.loads(reference_path.read_text())
    payload["execution_plan"] = json.loads(execution_plan_path.read_text())
    payload["room_synthesis"] = json.loads(synthesis_path.read_text())
    payload["approval_state"] = json.loads(approval_state_path.read_text())
    return payload


def render_host_payload(state, result: dict[str, object]) -> dict[str, object]:
    payload = render_ask_payload(state, result)
    host_decision = build_host_decision(state, result)
    payload["host_decision"] = host_decision.model_dump(mode="json")
    payload["host_decision_path"] = str(
        room_path(Path(state.workspace), state.room_id) / "artifacts" / "host_decision.json"
    )
    return payload


def read_room_artifact_json(state, name: str) -> dict[str, object] | None:
    path = room_path(Path(state.workspace), state.room_id) / "artifacts" / name
    if not path.exists():
        return None
    return json.loads(path.read_text())


def render_existing_room_payload(state, action: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "room_id": state.room_id,
        "action": action,
        "triage": None,
        "wake": None,
    }
    for key, filename in [
        ("execution_plan", "execution_plan.json"),
        ("room_synthesis", "room_synthesis.json"),
        ("approval_state", "approval_state.json"),
        ("main_agent_reference", "main_agent_reference.json"),
    ]:
        value = read_room_artifact_json(state, filename)
        if value is not None:
            payload[key] = value
    for key, filename in [("design", "design.md"), ("tasks", "tasks.md")]:
        path = room_path(Path(state.workspace), state.room_id) / "artifacts" / filename
        if path.exists():
            payload[key] = path.read_text()
    return payload


def render_codex_workflow(payload: dict[str, object]) -> dict[str, object]:
    decision = payload["host_decision"]
    next_step = decision["next_step"]
    room_id = payload["room_id"]
    workflow = {
        "room_id": room_id,
        "next_step": next_step,
        "status": "ready",
        "instruction": decision["command_hint"],
        "user_message": decision["reason"],
    }
    if next_step == "continue_solo":
        workflow["codex_action"] = "continue_main_session"
        workflow["user_message"] = "This task can stay in the main Codex session."
    elif (
        next_step == "execute"
        and payload.get("action") != "accepted"
        and "main_agent_reference" in payload
    ):
        workflow["codex_action"] = "execute_with_room_reference"
        workflow["instruction"] = (
            "Use main_agent_reference as advisory input. The main Codex session remains "
            "responsible for deciding and implementing the final changes."
        )
        if payload.get("wake"):
            workflow["reference_path"] = payload["wake"]["artifacts"]["main_agent_reference.json"]
        workflow["advisory_only"] = True
    elif next_step == "ask_user":
        workflow["codex_action"] = "present_room_output_for_approval"
        workflow["instruction"] = (
            "Present room_synthesis.json and approval_state.json to the user. "
            "Do not edit the workspace until approval_state.status is accepted."
        )
        workflow["synthesis_path"] = payload["wake"]["artifacts"]["room_synthesis.json"]
        workflow["approval_state_path"] = payload["wake"]["artifacts"]["approval_state.json"]
        workflow["approval_required"] = True
    elif next_step == "execute":
        workflow["codex_action"] = "execute_accepted_plan"
        workflow["instruction"] = (
            "Implement accepted room_synthesis tasks, then run the listed verification checks."
        )
        if "execution_context_path" in payload:
            workflow["execution_context_path"] = payload["execution_context_path"]
    elif next_step == "wake_again":
        workflow["codex_action"] = "wake_room_again"
        workflow["instruction"] = "Run another wake cycle with a narrower goal before editing."
    else:
        workflow["codex_action"] = "summarize_review_only"
        workflow["instruction"] = "Summarize the room findings without changing the workspace."
    return workflow


@app.command("host-ask")
def host_ask(
    task: Annotated[str, typer.Option(help="Task summary.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    room: Annotated[str | None, typer.Option(help="Existing room id.")] = None,
    goal: Annotated[str | None, typer.Option(help="Wake-cycle goal override.")] = None,
    force_wake: Annotated[
        bool, typer.Option(help="Wake participants even if triage says solo.")
    ] = False,
    rounds: Annotated[int, typer.Option(help="Number of two-agent rounds when waking.")] = 1,
    collaboration_pattern: Annotated[
        str,
        typer.Option(help="Agent collaboration pattern: draft_review_revise or parallel_opinion."),
    ] = "draft_review_revise",
    agent_a: Annotated[str, typer.Option(help="First Codex participant id.")] = "codex_agent_a",
    agent_b: Annotated[str, typer.Option(help="Second Codex participant id.")] = "codex_agent_b",
    codex_bin: Annotated[str, typer.Option(help="Codex CLI executable.")] = "codex",
    model: Annotated[
        str | None,
        typer.Option(help="Codex model override. Defaults to ROOM_CODEX_MODEL or gpt-5.4."),
    ] = None,
    timeout_seconds: Annotated[int, typer.Option(help="Timeout per agent invocation.")] = 600,
) -> None:
    """Run host-facing task routing and print a machine-readable decision."""

    state = room_state(workspace, room) if room else create_room(workspace, task)
    if room and task != state.task:
        record_turn(
            state,
            speaker_id=state.main_agent,
            content=f"New host ask: {task}",
            turn_type="HOST_ASK",
        )

    try:
        result = ask_room(
            state,
            ask_text=task,
            force_wake=force_wake,
            goal=goal,
            agent_a=agent_a,
            agent_b=agent_b,
            rounds=rounds,
            collaboration_pattern=collaboration_pattern,
            codex_bin=codex_bin,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    payload = render_host_payload(state, result)
    typer.echo(json.dumps(payload, indent=2))


@app.command("codex-ask")
def codex_ask(
    task: Annotated[str, typer.Option(help="Task summary.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    room: Annotated[str | None, typer.Option(help="Existing room id.")] = None,
    goal: Annotated[str | None, typer.Option(help="Wake-cycle goal override.")] = None,
    force_wake: Annotated[
        bool, typer.Option(help="Wake participants even if triage says solo.")
    ] = False,
    rounds: Annotated[int, typer.Option(help="Number of two-agent rounds when waking.")] = 1,
    collaboration_pattern: Annotated[
        str,
        typer.Option(help="Agent collaboration pattern: draft_review_revise or parallel_opinion."),
    ] = "draft_review_revise",
    agent_a: Annotated[str, typer.Option(help="First Codex participant id.")] = "codex_agent_a",
    agent_b: Annotated[str, typer.Option(help="Second Codex participant id.")] = "codex_agent_b",
    codex_bin: Annotated[str, typer.Option(help="Codex CLI executable.")] = "codex",
    model: Annotated[
        str | None,
        typer.Option(help="Codex model override. Defaults to ROOM_CODEX_MODEL or gpt-5.4."),
    ] = None,
    timeout_seconds: Annotated[int, typer.Option(help="Timeout per agent invocation.")] = 600,
) -> None:
    """Run the Codex-client workflow entrypoint and print a routing packet."""

    state = room_state(workspace, room) if room else create_room(workspace, task)
    approval_state = load_approval_state(state) if room and not force_wake else None
    if approval_state and approval_state.status == "accepted":
        result = {"room_id": state.room_id, "action": "accepted", "triage": None, "wake": None}
        payload = render_existing_room_payload(state, "accepted")
        host_decision = build_host_decision(state, result)
        execution_context = build_execution_context(state)
        payload["host_decision"] = host_decision.model_dump(mode="json")
        payload["host_decision_path"] = str(
            room_path(Path(state.workspace), state.room_id) / "artifacts" / "host_decision.json"
        )
        payload["execution_context"] = execution_context.model_dump(mode="json")
        payload["execution_context_path"] = str(
            room_path(Path(state.workspace), state.room_id) / "artifacts" / "execution_context.json"
        )
        payload["codex_workflow"] = render_codex_workflow(payload)
        typer.echo(json.dumps(payload, indent=2))
        return

    if room and task != state.task:
        record_turn(
            state,
            speaker_id=state.main_agent,
            content=f"New Codex ask: {task}",
            turn_type="CODEX_ASK",
        )

    try:
        result = ask_room(
            state,
            ask_text=task,
            force_wake=force_wake,
            goal=goal,
            agent_a=agent_a,
            agent_b=agent_b,
            rounds=rounds,
            collaboration_pattern=collaboration_pattern,
            codex_bin=codex_bin,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    payload = render_host_payload(state, result)
    payload["codex_workflow"] = render_codex_workflow(payload)
    typer.echo(json.dumps(payload, indent=2))


def read_text_preview(path: Path, max_chars: int = 4000) -> str:
    content = path.read_text()
    if len(content) <= max_chars:
        return content
    return content[:max_chars].rstrip() + "\n\n[truncated]"


@app.command("accept-plan")
def accept_plan_command(
    room: Annotated[str, typer.Option(help="Room id.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    actor: Annotated[str, typer.Option(help="Actor accepting the plan.")] = "codex_main",
    reason: Annotated[str | None, typer.Option(help="Optional acceptance reason.")] = None,
    task_id: Annotated[
        list[str] | None,
        typer.Option("--task-id", help="Specific synthesis task id to accept."),
    ] = None,
) -> None:
    """Accept a pending room synthesis proposal."""

    state = room_state(workspace, room)
    try:
        approval_state = accept_plan(
            state,
            actor=actor,
            reason=reason,
            task_ids=task_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(approval_state.model_dump(mode="json"), indent=2))


@app.command("reject-plan")
def reject_plan_command(
    room: Annotated[str, typer.Option(help="Room id.")],
    reason: Annotated[str, typer.Option(help="Why the proposal is rejected.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    actor: Annotated[str, typer.Option(help="Actor rejecting the plan.")] = "codex_main",
    task_id: Annotated[
        list[str] | None,
        typer.Option("--task-id", help="Specific synthesis task id to reject."),
    ] = None,
) -> None:
    """Reject a pending room synthesis proposal."""

    state = room_state(workspace, room)
    try:
        approval_state = reject_plan(
            state,
            actor=actor,
            reason=reason,
            task_ids=task_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(approval_state.model_dump(mode="json"), indent=2))


@app.command("execution-context")
def execution_context_command(
    room: Annotated[str, typer.Option(help="Room id.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
) -> None:
    """Emit execution context for an accepted room synthesis."""

    state = room_state(workspace, room)
    try:
        context = build_execution_context(state)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(context.model_dump(mode="json"), indent=2))


@app.command("reference-context")
def reference_context_command(
    room: Annotated[str, typer.Option(help="Room id.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
) -> None:
    """Emit the latest advisory packet for the main agent."""

    state = room_state(workspace, room)
    reference = load_main_agent_reference(state)
    if not reference:
        raise typer.BadParameter("main_agent_reference.json not found")
    typer.echo(json.dumps(reference.model_dump(mode="json"), indent=2))


@app.command()
def attach(
    room: Annotated[str, typer.Option(help="Room id.")],
    kind: Annotated[ParticipantKind, typer.Option(help="Participant kind.")],
    participant_id: Annotated[str, typer.Option("--id", help="Participant id.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    label: Annotated[str | None, typer.Option(help="Human-readable label.")] = None,
    capability: Annotated[list[str] | None, typer.Option(help="Capability to add.")] = None,
    permission: Annotated[list[str] | None, typer.Option(help="Permission to add.")] = None,
    status: Annotated[str | None, typer.Option(help="Initial participant status.")] = None,
    cost_tier: Annotated[str | None, typer.Option(help="Optional cost tier.")] = None,
) -> None:
    """Attach a participant to a room."""

    state = room_state(workspace, room)
    try:
        participant = attach_participant(
            state,
            participant_id=participant_id,
            kind=kind,
            label=label,
            capabilities=capability,
            permissions=permission,
            status=status,
            cost_tier=cost_tier,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(JSON(participant.model_dump_json(indent=2)))


@app.command()
def say(
    room: Annotated[str, typer.Option(help="Room id.")],
    speaker: Annotated[str, typer.Option(help="Speaker participant id.")],
    content: Annotated[str, typer.Option(help="Message content.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    turn_type: Annotated[str, typer.Option("--type", help="Transcript turn type.")] = "MESSAGE",
    evidence: Annotated[list[str] | None, typer.Option(help="Evidence reference.")] = None,
    confidence: Annotated[float | None, typer.Option(help="Optional confidence 0-1.")] = None,
) -> None:
    """Append a transcript turn."""

    state = room_state(workspace, room)
    turn = record_turn(
        state,
        speaker_id=speaker,
        content=content,
        turn_type=turn_type,
        evidence=evidence,
        confidence=confidence,
    )
    console.print(f"recorded turn {turn.turn_id}")


@app.command("add-evidence")
def add_evidence(
    room: Annotated[str, typer.Option(help="Room id.")],
    source: Annotated[str, typer.Option(help="Evidence source, such as file:path or url.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    summary: Annotated[str | None, typer.Option(help="Short evidence summary.")] = None,
    content: Annotated[str | None, typer.Option(help="Optional captured content.")] = None,
    added_by: Annotated[
        str, typer.Option(help="Participant id that added the evidence.")
    ] = "codex_main",
) -> None:
    """Append an evidence entry."""

    state = room_state(workspace, room)
    evidence = record_evidence(
        state,
        source=source,
        summary=summary,
        content=content,
        added_by=added_by,
    )
    console.print(f"recorded evidence {evidence.evidence_id}")


@app.command()
def decide(
    room: Annotated[str, typer.Option(help="Room id.")],
    decision: Annotated[str, typer.Option(help="Chosen decision.")],
    why: Annotated[str, typer.Option(help="Why this decision was chosen.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    owner: Annotated[str, typer.Option(help="Decision owner.")] = "codex_main",
    rejected: Annotated[list[str] | None, typer.Option(help="Rejected alternative.")] = None,
    risk: Annotated[list[str] | None, typer.Option(help="Accepted risk.")] = None,
) -> None:
    """Record a main-agent decision."""

    state = room_state(workspace, room)
    entry = record_decision(
        state,
        decision=decision,
        why=why,
        owner=owner,
        alternatives_rejected=rejected,
        accepted_risks=risk,
    )
    console.print(f"recorded decision {entry.decision_id}")


@app.command()
def artifact(
    room: Annotated[str, typer.Option(help="Room id.")],
    name: Annotated[str, typer.Option(help="Artifact filename.")],
    content: Annotated[str, typer.Option(help="Artifact content.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
) -> None:
    """Write a room artifact."""

    state = room_state(workspace, room)
    try:
        path = write_artifact(state, name, content)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"wrote artifact {path}")


@app.command()
def report(
    room: Annotated[str, typer.Option(help="Room id.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
) -> None:
    """Generate and print the final room report."""

    state = room_state(workspace, room)
    console.print(generate_report(state))


@app.command()
def serve(
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    host: Annotated[str, typer.Option(help="Host to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to bind.")] = 8765,
) -> None:
    """Serve a read-only local web observer for rooms."""

    url = f"http://{host}:{port}"
    console.print(f"serving room observer at {url}")
    console.print("press Ctrl-C to stop")
    try:
        serve_observer(workspace, host, port)
    except KeyboardInterrupt:
        console.print("stopped room observer")


@app.command()
def close(
    room: Annotated[str, typer.Option(help="Room id.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    final_status: Annotated[
        str, typer.Option("--status", help="Final room status, such as DONE or ABANDONED.")
    ] = "DONE",
    reason: Annotated[str | None, typer.Option(help="Optional close reason.")] = None,
) -> None:
    """Close a room and generate its final report."""

    state = room_state(workspace, room)
    close_room(state, final_status=final_status, reason=reason)
    console.print(f"closed room {state.room_id} as {state.status}")
    report_path = room_path(Path(state.workspace), state.room_id) / "reports" / "final.md"
    console.print(f"report: {report_path}")


@app.command()
def play(
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    room: Annotated[str | None, typer.Option(help="Existing room id.")] = None,
    task: Annotated[str | None, typer.Option(help="Task summary when creating a new room.")] = None,
    rounds: Annotated[int, typer.Option(help="Number of two-agent rounds to run.")] = 1,
    collaboration_pattern: Annotated[
        str,
        typer.Option(help="Agent collaboration pattern: draft_review_revise or parallel_opinion."),
    ] = "draft_review_revise",
    agent_a: Annotated[str, typer.Option(help="First Codex participant id.")] = "codex_agent_a",
    agent_b: Annotated[str, typer.Option(help="Second Codex participant id.")] = "codex_agent_b",
    codex_bin: Annotated[str, typer.Option(help="Codex CLI executable.")] = "codex",
    model: Annotated[
        str | None,
        typer.Option(help="Codex model override. Defaults to ROOM_CODEX_MODEL or gpt-5.4."),
    ] = None,
    timeout_seconds: Annotated[int, typer.Option(help="Timeout per agent invocation.")] = 600,
) -> None:
    """Run two Codex CLI agents in the room."""

    if room:
        state = room_state(workspace, room)
    else:
        if not task:
            raise typer.BadParameter("--task is required when --room is not provided")
        state = create_room(workspace, task)

    try:
        turns = play_codex_agents(
            state,
            agent_a=agent_a,
            agent_b=agent_b,
            rounds=rounds,
            collaboration_pattern=collaboration_pattern,
            codex_bin=codex_bin,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    console.print(f"played {len(turns)} agent turns in {state.room_id}")
    report_path = room_path(Path(state.workspace), state.room_id) / "reports" / "final.md"
    console.print(f"report: {report_path}")


@app.command()
def wake(
    goal: Annotated[str, typer.Option(help="Wake-cycle goal.")],
    workspace: Annotated[Path, typer.Option(help="Workspace path.")] = Path("."),
    room: Annotated[str | None, typer.Option(help="Existing room id.")] = None,
    task: Annotated[str | None, typer.Option(help="Task summary when creating a new room.")] = None,
    rounds: Annotated[int, typer.Option(help="Number of two-agent rounds to run.")] = 1,
    collaboration_pattern: Annotated[
        str,
        typer.Option(help="Agent collaboration pattern: draft_review_revise or parallel_opinion."),
    ] = "draft_review_revise",
    agent_a: Annotated[str, typer.Option(help="First Codex participant id.")] = "codex_agent_a",
    agent_b: Annotated[str, typer.Option(help="Second Codex participant id.")] = "codex_agent_b",
    codex_bin: Annotated[str, typer.Option(help="Codex CLI executable.")] = "codex",
    model: Annotated[
        str | None,
        typer.Option(help="Codex model override. Defaults to ROOM_CODEX_MODEL or gpt-5.4."),
    ] = None,
    timeout_seconds: Annotated[int, typer.Option(help="Timeout per agent invocation.")] = 600,
) -> None:
    """Wake room participants for one discussion/capture cycle."""

    if room:
        state = room_state(workspace, room)
    else:
        if not task:
            raise typer.BadParameter("--task is required when --room is not provided")
        state = create_room(workspace, task)

    try:
        result = wake_room(
            state,
            goal=goal,
            agent_a=agent_a,
            agent_b=agent_b,
            rounds=rounds,
            collaboration_pattern=collaboration_pattern,
            codex_bin=codex_bin,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except (RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    console.print(
        f"woke {state.room_id} with {result['turns']} agent turns in {result['cycle_id']}"
    )
    console.print(f"design: {result['artifacts']['design.md']}")
    console.print(f"tasks: {result['artifacts']['tasks.md']}")
