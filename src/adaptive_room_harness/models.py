from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


ParticipantKind = Literal["agent", "subagent", "tool", "workflow", "memory", "database", "human"]
ParticipantStatus = Literal["active", "sleeping", "available", "inactive"]
RoomMode = Literal[
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
]
RiskLevel = Literal["low", "medium", "high"]
ResumeStatus = Literal["authoritative", "partial", "stale"]
RecommendedAction = Literal["implement", "ask_user", "research_more", "review_only"]
HostNextStep = Literal["continue_solo", "ask_user", "execute", "wake_again", "review_only"]
ApprovalStatus = Literal["not_required", "pending", "accepted", "rejected", "superseded"]
ReferenceConfidence = Literal["low", "medium", "high"]
CollaborationPattern = Literal["parallel_opinion", "draft_review_revise", "mixed_runtime_review"]


class RoomState(BaseModel):
    room_id: str
    workspace: str
    task: str
    status: str = "DISCUSSION"
    mode: RoomMode = "triage"
    main_agent: str = "codex_main"
    risk_level: RiskLevel = "low"
    activation_policy: str = "on_demand"
    collaboration_pattern: CollaborationPattern = "draft_review_revise"
    max_rounds: int = 4
    current_round: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Participant(BaseModel):
    id: str
    kind: ParticipantKind
    label: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    status: ParticipantStatus = "available"
    cost_tier: str | None = None


class TranscriptTurn(BaseModel):
    room_id: str
    turn_id: int
    speaker_id: str
    speaker_kind: ParticipantKind | str = "agent"
    type: str = "MESSAGE"
    content: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float | None = None
    created_at: datetime = Field(default_factory=utc_now)


class EvidenceEntry(BaseModel):
    room_id: str
    evidence_id: str
    source: str
    summary: str | None = None
    content: str | None = None
    added_by: str = "codex_main"
    created_at: datetime = Field(default_factory=utc_now)


class DecisionEntry(BaseModel):
    room_id: str
    decision_id: str
    owner: str = "codex_main"
    decision: str
    why: str
    alternatives_rejected: list[str] = Field(default_factory=list)
    accepted_risks: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class SuggestedParticipant(BaseModel):
    id: str
    reason: str


class TriageResult(BaseModel):
    need_activation: bool
    risk_level: RiskLevel
    uncertainty_level: RiskLevel
    recommended_mode: RoomMode
    suggested_participants: list[SuggestedParticipant] = Field(default_factory=list)
    solo_reason_if_no_activation: str | None = None


class WakeCheckpoint(BaseModel):
    room_id: str
    source_cycle: str
    resume_status: ResumeStatus = "authoritative"
    wake_goal: str
    stable_resume: list[str] = Field(default_factory=list)
    pending_tasks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    artifact_pointers: dict[str, str] = Field(default_factory=dict)
    written_at: datetime = Field(default_factory=utc_now)


class ExecutionTask(BaseModel):
    id: str
    title: str
    status: str = "pending"
    acceptance: list[str] = Field(default_factory=list)
    risk: RiskLevel = "medium"


class WakeExecutionPlan(BaseModel):
    room_id: str
    source_cycle: str
    summary: str
    recommended_action: RecommendedAction
    tasks: list[ExecutionTask] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    requires_user_approval: bool = True
    artifact_pointers: dict[str, str] = Field(default_factory=dict)
    written_at: datetime = Field(default_factory=utc_now)


class SynthesisOption(BaseModel):
    id: str
    title: str
    summary: str
    tradeoffs: list[str] = Field(default_factory=list)


class SynthesisTask(BaseModel):
    id: str
    title: str
    acceptance: list[str] = Field(default_factory=list)
    risk: RiskLevel = "medium"


class SynthesisRisk(BaseModel):
    id: str
    summary: str
    mitigation: str | None = None
    level: RiskLevel = "medium"


class RoomSynthesis(BaseModel):
    room_id: str
    synthesis_id: str
    source_cycle: str
    task: str
    problem_summary: str
    participants: list[str] = Field(default_factory=list)
    options: list[SynthesisOption] = Field(default_factory=list)
    recommended_path: str
    why_this_path: str
    risks: list[SynthesisRisk] = Field(default_factory=list)
    tasks: list[SynthesisTask] = Field(default_factory=list)
    approval_required: bool = True
    approval_questions: list[str] = Field(default_factory=list)
    artifact_pointers: dict[str, str] = Field(default_factory=dict)
    written_at: datetime = Field(default_factory=utc_now)


class ApprovalState(BaseModel):
    room_id: str
    synthesis_id: str
    status: ApprovalStatus = "pending"
    actor: str = "codex_main"
    reason: str | None = None
    accepted_task_ids: list[str] = Field(default_factory=list)
    rejected_task_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExecutionContext(BaseModel):
    room_id: str
    synthesis_id: str
    accepted_task_ids: list[str] = Field(default_factory=list)
    implementation_brief: str
    risks: list[SynthesisRisk] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)
    artifact_pointers: dict[str, str] = Field(default_factory=dict)
    written_at: datetime = Field(default_factory=utc_now)


class MainAgentReference(BaseModel):
    schema_version: int = 1
    room_id: str
    reference_id: str
    source_cycle: str
    task: str
    objective: str
    advisory_only: bool = True
    confidence: ReferenceConfidence = "medium"
    recommended_focus: str
    key_points: list[str] = Field(default_factory=list)
    suggested_steps: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)
    artifact_pointers: dict[str, str] = Field(default_factory=dict)
    written_at: datetime = Field(default_factory=utc_now)


class HostDecision(BaseModel):
    room_id: str
    next_step: HostNextStep
    reason: str
    recommended_action: RecommendedAction | None = None
    requires_user_approval: bool = False
    artifact_pointers: dict[str, str] = Field(default_factory=dict)
    command_hint: str | None = None
    written_at: datetime = Field(default_factory=utc_now)
