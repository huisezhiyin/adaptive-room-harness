from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AgentRuntime = Literal["codex-cli", "claude-cli", "anthropic-api"]


@dataclass(frozen=True)
class CodexExecResult:
    command: list[str]
    output: str


DEFAULT_CODEX_MODEL = "gpt-5.4"
CODEX_MODEL_ENV = "ROOM_CODEX_MODEL"
DEFAULT_CLAUDE_MODEL = "sonnet"
CLAUDE_MODEL_ENV = "ROOM_CLAUDE_MODEL"
CLAUDE_PROVIDER_ENV = "ROOM_CLAUDE_PROVIDER"
CLAUDE_API_KEY_ENV_ENV = "ROOM_CLAUDE_API_KEY_ENV"
CLAUDE_BARE_ENV = "ROOM_CLAUDE_BARE"
CLAUDE_DEEPSEEK_MODEL_ENV = "ROOM_CLAUDE_DEEPSEEK_MODEL"
DEFAULT_ANTHROPIC_MODEL = "deepseek-v4-pro"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
ANTHROPIC_MODEL_ENV = "ROOM_ANTHROPIC_MODEL"
ANTHROPIC_BASE_URL_ENV = "ROOM_ANTHROPIC_BASE_URL"
ANTHROPIC_API_KEY_ENV_ENV = "ROOM_ANTHROPIC_API_KEY_ENV"
ANTHROPIC_MAX_TOKENS_ENV = "ROOM_ANTHROPIC_MAX_TOKENS"


def resolve_codex_model(model: str | None = None) -> str:
    if model:
        return model
    env_model = os.environ.get(CODEX_MODEL_ENV)
    if env_model:
        return env_model
    return DEFAULT_CODEX_MODEL


def resolve_claude_model(model: str | None = None) -> str:
    if model:
        return model
    env_model = os.environ.get(CLAUDE_MODEL_ENV)
    if env_model:
        return env_model
    return DEFAULT_CLAUDE_MODEL


def claude_uses_deepseek() -> bool:
    return os.environ.get(CLAUDE_PROVIDER_ENV, "").strip().lower() == "deepseek"


def resolve_claude_api_key_env() -> str:
    return os.environ.get(CLAUDE_API_KEY_ENV_ENV) or resolve_anthropic_api_key_env()


def build_claude_deepseek_vars() -> dict[str, str]:
    env_name = resolve_claude_api_key_env()
    api_key = os.environ.get(env_name)
    if not api_key:
        raise RuntimeError(f"{env_name} is not set")

    model = os.environ.get(CLAUDE_DEEPSEEK_MODEL_ENV) or resolve_anthropic_model()
    return {
        "ANTHROPIC_BASE_URL": resolve_anthropic_base_url(),
        "ANTHROPIC_AUTH_TOKEN": api_key,
        "ANTHROPIC_API_KEY": api_key,
        "ANTHROPIC_MODEL": model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash",
        "CLAUDE_CODE_SUBAGENT_MODEL": "deepseek-v4-flash",
        "CLAUDE_CODE_EFFORT_LEVEL": os.environ.get("CLAUDE_CODE_EFFORT_LEVEL", "max"),
    }


def build_claude_env() -> dict[str, str]:
    env = os.environ.copy()
    if not claude_uses_deepseek():
        return env

    env.update(build_claude_deepseek_vars())
    return env


def write_claude_settings_file() -> str | None:
    if not claude_uses_deepseek():
        return None

    settings_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
    with settings_file:
        json.dump({"env": build_claude_deepseek_vars()}, settings_file)
    return settings_file.name


def resolve_anthropic_model(model: str | None = None) -> str:
    if model:
        return model
    env_model = os.environ.get(ANTHROPIC_MODEL_ENV)
    if env_model:
        return env_model
    return DEFAULT_ANTHROPIC_MODEL


def resolve_anthropic_base_url(base_url: str | None = None) -> str:
    if base_url:
        return base_url
    env_base_url = os.environ.get(ANTHROPIC_BASE_URL_ENV)
    if env_base_url:
        return env_base_url
    return DEFAULT_ANTHROPIC_BASE_URL


def resolve_anthropic_api_key_env(api_key_env: str | None = None) -> str:
    if api_key_env:
        return api_key_env
    env_name = os.environ.get(ANTHROPIC_API_KEY_ENV_ENV)
    if env_name:
        return env_name
    return "DEEPSEEK_API_KEY"


def resolve_anthropic_max_tokens(max_tokens: int | None = None) -> int:
    if max_tokens:
        return max_tokens
    env_value = os.environ.get(ANTHROPIC_MAX_TOKENS_ENV)
    if env_value:
        return int(env_value)
    return 2000


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

Output contract:
- Start with the concrete result for your collaboration step.
- Include a `Recommendation:` line when you have a preferred path.
- Include `Suggested steps:` and `Verification:` when implementation or review follow-up is useful.
- Include `Risks:` for concrete failure modes, not generic caution.
- For review/final-check steps, lead with blocking findings. If there are no blocking findings, say so explicitly before listing non-blocking risks.
- Treat the main Codex session as owner, decider, implementer, and verifier. Your output is advisory only.

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
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"codex executable not found: {executable}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"codex exec timed out after {timeout_seconds} seconds"
            ) from exc
        output_file.seek(0)
        output = output_file.read().strip()

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"codex exec failed with exit code {completed.returncode}: {detail}")

    if not output:
        output = completed.stdout.strip()
    return CodexExecResult(command=command, output=output.strip())


def run_anthropic_messages(
    *,
    prompt: str,
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    max_tokens: int | None = None,
    timeout_seconds: int = 600,
) -> CodexExecResult:
    env_name = resolve_anthropic_api_key_env(api_key_env)
    api_key = os.environ.get(env_name)
    if not api_key:
        raise RuntimeError(f"{env_name} is not set")

    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic package is not installed") from exc

    effective_model = resolve_anthropic_model(model)
    effective_base_url = resolve_anthropic_base_url(base_url)
    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=effective_base_url,
        timeout=timeout_seconds,
    )
    message = client.messages.create(
        model=effective_model,
        max_tokens=resolve_anthropic_max_tokens(max_tokens),
        system="You are a careful coding-agent room participant.",
        messages=[
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
    )
    output_parts: list[str] = []
    for block in message.content:
        text = getattr(block, "text", None)
        if text:
            output_parts.append(text)
    output = "\n".join(output_parts).strip()
    return CodexExecResult(
        command=[
            "anthropic-messages",
            "--base-url",
            effective_base_url,
            "--model",
            effective_model,
            "--api-key-env",
            env_name,
        ],
        output=output,
    )


def run_claude_print(
    *,
    claude_bin: str,
    workspace: Path,
    prompt: str,
    model: str | None = None,
    timeout_seconds: int = 600,
) -> CodexExecResult:
    executable = shutil.which(claude_bin) or claude_bin
    effective_model = resolve_claude_model(model)
    command = [executable]
    settings_path = write_claude_settings_file()
    if settings_path:
        command.extend(["--settings", settings_path])
    if os.environ.get(CLAUDE_BARE_ENV, "").strip().lower() in {"1", "true", "yes"}:
        command.append("--bare")
    command.extend(
        [
            "-p",
            "--output-format",
            "text",
            "--no-session-persistence",
            "--permission-mode",
            "plan",
            "--tools",
            "",
            "--model",
            effective_model,
            prompt,
        ]
    )
    try:
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                env=build_claude_env(),
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"claude executable not found: {executable}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"claude -p timed out after {timeout_seconds} seconds"
            ) from exc
    finally:
        if settings_path:
            Path(settings_path).unlink(missing_ok=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"claude -p failed with exit code {completed.returncode}: {detail}")
    return CodexExecResult(command=command[:-1] + ["<prompt>"], output=completed.stdout.strip())


def run_agent_runtime(
    *,
    runtime: AgentRuntime,
    codex_bin: str,
    claude_bin: str,
    workspace: Path,
    prompt: str,
    model: str | None = None,
    timeout_seconds: int = 600,
    anthropic_base_url: str | None = None,
    anthropic_api_key_env: str | None = None,
    anthropic_max_tokens: int | None = None,
) -> CodexExecResult:
    if runtime == "codex-cli":
        return run_codex_exec(
            codex_bin=codex_bin,
            workspace=workspace,
            prompt=prompt,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    if runtime == "claude-cli":
        return run_claude_print(
            claude_bin=claude_bin,
            workspace=workspace,
            prompt=prompt,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    if runtime == "anthropic-api":
        return run_anthropic_messages(
            prompt=prompt,
            model=model,
            base_url=anthropic_base_url,
            api_key_env=anthropic_api_key_env,
            max_tokens=anthropic_max_tokens,
            timeout_seconds=timeout_seconds,
        )
    raise RuntimeError(f"unsupported agent runtime: {runtime}")
