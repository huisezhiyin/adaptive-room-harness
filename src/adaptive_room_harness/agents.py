from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CodexExecResult:
    command: list[str]
    output: str


DEFAULT_CODEX_MODEL = "gpt-5.4"
CODEX_MODEL_ENV = "ROOM_CODEX_MODEL"


def resolve_codex_model(model: str | None = None) -> str:
    if model:
        return model
    env_model = os.environ.get(CODEX_MODEL_ENV)
    if env_model:
        return env_model
    return DEFAULT_CODEX_MODEL


def render_agent_prompt(
    *,
    room_id: str,
    task: str,
    agent_id: str,
    peer_id: str,
    round_number: int,
    collaboration_pattern: str,
    collaboration_step: str,
    step_instruction: str,
    transcript_excerpt: str,
) -> str:
    return f"""You are participant `{agent_id}` in Adaptive Room Harness room `{room_id}`.

Task:
{task}

Peer participant:
{peer_id}

Round:
{round_number}

Collaboration pattern:
{collaboration_pattern}

Your collaboration step:
{collaboration_step}

Step instruction:
{step_instruction}

Recent room transcript:
{transcript_excerpt or "(No prior transcript.)"}

Respond as `{agent_id}` only. Stay in your assigned collaboration step.

Do not modify files. Do not ask the user for input. End with one short "Next:" line.
"""


def run_codex_exec(
    *,
    codex_bin: str,
    workspace: Path,
    prompt: str,
    model: str | None = None,
    timeout_seconds: int = 600,
) -> CodexExecResult:
    executable = shutil.which(codex_bin) or codex_bin
    effective_model = resolve_codex_model(model)
    command = [
        executable,
        "exec",
        "--cd",
        str(workspace),
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "--color",
        "never",
        "--model",
        effective_model,
    ]

    with tempfile.NamedTemporaryFile("r+", encoding="utf-8") as output_file:
        command.extend(["--output-last-message", output_file.name, "-"])
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        output_file.seek(0)
        output = output_file.read().strip()

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"codex exec failed with exit code {completed.returncode}: {detail}")

    if not output:
        output = completed.stdout.strip()
    return CodexExecResult(command=command, output=output.strip())
