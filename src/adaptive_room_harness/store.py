from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from adaptive_room_harness.models import (
    DecisionEntry,
    EvidenceEntry,
    Participant,
    RoomState,
    TranscriptTurn,
    utc_now,
)

T = TypeVar("T", bound=BaseModel)


ROOM_ROOT = ".room"


def json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def dump_json(path: Path, value: BaseModel | list[BaseModel] | dict[str, object]) -> None:
    if isinstance(value, BaseModel):
        payload: object = value.model_dump(mode="json")
    elif isinstance(value, list):
        payload = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in value
        ]
    else:
        payload = value
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=json_default) + "\n")


def load_json(path: Path, model: type[T]) -> T:
    return model.model_validate_json(path.read_text())


def load_json_list(path: Path, model: type[T]) -> list[T]:
    return [model.model_validate(item) for item in json.loads(path.read_text())]


def append_jsonl(path: Path, value: BaseModel) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(value.model_dump_json() + "\n")


def read_jsonl(path: Path, model: type[T]) -> list[T]:
    if not path.exists():
        return []
    return [
        model.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()
    ]


def room_base(workspace: Path) -> Path:
    return workspace / ROOM_ROOT / "rooms"


def room_path(workspace: Path, room_id: str) -> Path:
    return room_base(workspace) / room_id


def make_room_id(workspace: Path, now: datetime | None = None) -> str:
    stamp = (now or utc_now()).astimezone(UTC).strftime("%Y%m%d_%H%M%S")
    base = f"room_{stamp}"
    candidate = base
    index = 1
    while room_path(workspace, candidate).exists():
        index += 1
        candidate = f"{base}_{index:02d}"
    return candidate


def default_participants() -> list[Participant]:
    return [
        Participant(
            id="codex_main",
            kind="agent",
            label="Main Agent",
            capabilities=["reasoning", "coding", "planning", "review"],
            permissions=["read_workspace", "write_workspace", "write_artifact", "decide", "admin"],
            status="active",
        ),
        Participant(
            id="websearch",
            kind="tool",
            label="Web Search",
            capabilities=["web_search", "fetch"],
            permissions=["search_network"],
            status="available",
        ),
        Participant(
            id="sdd",
            kind="workflow",
            label="SDD Workflow",
            capabilities=["spec_write", "checkpoint", "task_decompose"],
            permissions=["write_artifact"],
            status="available",
        ),
        Participant(
            id="expcap",
            kind="memory",
            label="Experience Capitalization",
            capabilities=["memory_recall", "memory_capture"],
            permissions=["read_memory", "write_memory_candidate"],
            status="available",
        ),
    ]


def create_room(workspace: Path, task: str) -> RoomState:
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    room_id = make_room_id(workspace)
    path = room_path(workspace, room_id)
    for child in [
        path / "artifacts",
        path / "cycles",
        path / "reports",
        path / "cache",
        path / "sdd",
        path / "patches",
    ]:
        child.mkdir(parents=True, exist_ok=True)

    state = RoomState(room_id=room_id, workspace=str(workspace), task=task)
    dump_json(path / "state.json", state)
    dump_json(path / "participants.json", default_participants())
    dump_json(path / "permissions.json", {"owner": "codex_main", "default_writer": "codex_main"})
    dump_json(
        path / "modes.json",
        {
            "current": state.mode,
            "available": [
                "solo",
                "triage",
                "open_council",
                "role_bounded",
                "pair_programming",
                "red_team",
                "review_board",
                "research_sprint",
                "sdd_spec",
                "execution_support",
            ],
        },
    )
    (path / "goal.md").write_text(f"# Goal\n\n{task}\n")
    for log_name in ["transcript.jsonl", "evidence.jsonl", "decisions.jsonl"]:
        (path / log_name).touch()
    return state


def save_state(state: RoomState) -> None:
    state.updated_at = utc_now()
    dump_json(room_path(Path(state.workspace), state.room_id) / "state.json", state)


def load_state(workspace: Path, room_id: str) -> RoomState:
    return load_json(room_path(workspace.resolve(), room_id) / "state.json", RoomState)


def list_states(workspace: Path) -> list[RoomState]:
    base = room_base(workspace.resolve())
    if not base.exists():
        return []

    states = []
    for path in sorted(base.iterdir()):
        state_path = path / "state.json"
        if path.is_dir() and state_path.exists():
            try:
                states.append(load_json(state_path, RoomState))
            except (json.JSONDecodeError, ValidationError):
                continue
    return sorted(states, key=lambda state: state.created_at, reverse=True)


def load_participants(state: RoomState) -> list[Participant]:
    return load_json_list(
        room_path(Path(state.workspace), state.room_id) / "participants.json", Participant
    )


def save_participants(state: RoomState, participants: Iterable[Participant]) -> None:
    dump_json(
        room_path(Path(state.workspace), state.room_id) / "participants.json", list(participants)
    )


def next_turn_id(state: RoomState) -> int:
    return len(read_transcript(state)) + 1


def next_evidence_id(state: RoomState) -> str:
    return f"ev_{len(read_evidence(state)) + 1:03d}"


def next_decision_id(state: RoomState) -> str:
    return f"dec_{len(read_decisions(state)) + 1:03d}"


def append_transcript(state: RoomState, turn: TranscriptTurn) -> None:
    append_jsonl(room_path(Path(state.workspace), state.room_id) / "transcript.jsonl", turn)


def append_evidence(state: RoomState, evidence: EvidenceEntry) -> None:
    append_jsonl(room_path(Path(state.workspace), state.room_id) / "evidence.jsonl", evidence)


def append_decision(state: RoomState, decision: DecisionEntry) -> None:
    append_jsonl(room_path(Path(state.workspace), state.room_id) / "decisions.jsonl", decision)


def read_transcript(state: RoomState) -> list[TranscriptTurn]:
    return read_jsonl(
        room_path(Path(state.workspace), state.room_id) / "transcript.jsonl", TranscriptTurn
    )


def read_evidence(state: RoomState) -> list[EvidenceEntry]:
    return read_jsonl(
        room_path(Path(state.workspace), state.room_id) / "evidence.jsonl", EvidenceEntry
    )


def read_decisions(state: RoomState) -> list[DecisionEntry]:
    return read_jsonl(
        room_path(Path(state.workspace), state.room_id) / "decisions.jsonl", DecisionEntry
    )
