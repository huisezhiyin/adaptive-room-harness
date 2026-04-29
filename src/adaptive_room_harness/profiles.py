from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

from adaptive_room_harness.agents import AgentRuntime

DEFAULT_PROFILE_FILE = ".room-profiles.toml"


class ParticipantProfile(BaseModel):
    id: str
    runtime: AgentRuntime
    model: str | None = None
    role: str
    authority: str = "advisor"
    weight: float = 1.0
    can_block: bool = False
    bin: str | None = None
    api_base_url: str | None = None
    capabilities: dict[str, float] = Field(default_factory=dict)


class RoomProfile(BaseModel):
    name: str
    description: str | None = None
    pattern: str = "parallel_opinion"
    rounds: int = 1
    participants: list[ParticipantProfile]


def load_room_profile(workspace: Path, profile_name: str) -> RoomProfile:
    path = resolve_profile_config_path(workspace)
    data = tomllib.loads(path.read_text())
    profile_data = data.get("profiles", {}).get(profile_name)
    if not profile_data:
        raise ValueError(f"profile not found: {profile_name}")
    payload = {"name": profile_name, **profile_data}
    profile = RoomProfile.model_validate(payload)
    if len(profile.participants) < 2:
        raise ValueError(f"profile {profile_name} must define at least two participants")
    return profile


def resolve_profile_config_path(workspace: Path) -> Path:
    candidates = []
    env_path = os.environ.get("ROOM_PROFILES_FILE")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.extend(
        [
            workspace / DEFAULT_PROFILE_FILE,
            Path(__file__).resolve().parents[2] / DEFAULT_PROFILE_FILE,
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    searched = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"profile config not found; searched: {searched}")


def render_profile_context(profile: RoomProfile) -> str:
    lines = [
        f"Room profile: {profile.name}",
        f"Description: {profile.description or '(none)'}",
        f"Pattern: {profile.pattern}",
        "",
        "Participants:",
    ]
    for participant in profile.participants:
        caps = ", ".join(
            f"{name}={score}" for name, score in sorted(participant.capabilities.items())
        )
        lines.extend(
            [
                f"- {participant.id}",
                f"  runtime: {participant.runtime}",
                f"  model: {participant.model or '(runtime default)'}",
                f"  role: {participant.role}",
                f"  authority: {participant.authority}",
                f"  weight: {participant.weight}",
                f"  can_block: {participant.can_block}",
                f"  capabilities: {caps or '(unspecified)'}",
            ]
        )
    lines.extend(
        [
            "",
            "Authority rule:",
            "Treat lower-weight participants as advisory. They may add ideas, risks, "
            "and objections, but the main agent remains responsible for final judgment, "
            "execution, and verification.",
        ]
    )
    return "\n".join(lines)
