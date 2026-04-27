import json
import types
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen

from typer.testing import CliRunner

from adaptive_room_harness.cli import app
from adaptive_room_harness.profiles import load_room_profile
from adaptive_room_harness.server import build_room_payload, make_handler

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_room_mvp_command_flow(tmp_path) -> None:
    workspace = tmp_path / "workspace"

    init_result = runner.invoke(
        app,
        [
            "init",
            "--workspace",
            str(workspace),
            "--task",
            "Evaluate database migration rollback risk",
        ],
    )

    assert init_result.exit_code == 0
    room_id = next(part for part in init_result.stdout.split() if part.startswith("room_"))
    room_path = workspace / ".room" / "rooms" / room_id
    assert (room_path / "state.json").exists()
    assert (room_path / "participants.json").exists()
    assert (room_path / "transcript.jsonl").exists()

    triage_result = runner.invoke(
        app,
        ["triage", "--workspace", str(workspace), "--room", room_id],
    )

    assert triage_result.exit_code == 0
    assert "review_board" in triage_result.stdout
    assert (room_path / "artifacts" / "triage_result.md").exists()

    attach_result = runner.invoke(
        app,
        [
            "attach",
            "--workspace",
            str(workspace),
            "--room",
            room_id,
            "--kind",
            "agent",
            "--id",
            "claude_peer",
            "--capability",
            "review",
            "--permission",
            "comment",
        ],
    )

    assert attach_result.exit_code == 0
    assert "claude_peer" in (room_path / "participants.json").read_text()

    say_result = runner.invoke(
        app,
        [
            "say",
            "--workspace",
            str(workspace),
            "--room",
            room_id,
            "--speaker",
            "codex_main",
            "--content",
            "We need a rollback-safe plan.",
        ],
    )

    assert say_result.exit_code == 0
    assert "rollback-safe" in (room_path / "transcript.jsonl").read_text()

    evidence_result = runner.invoke(
        app,
        [
            "add-evidence",
            "--workspace",
            str(workspace),
            "--room",
            room_id,
            "--source",
            "file:docs/TECHNICAL_ARCHITECTURE.md",
            "--summary",
            "MVP uses filesystem and JSONL contracts.",
        ],
    )

    assert evidence_result.exit_code == 0
    assert "TECHNICAL_ARCHITECTURE" in (room_path / "evidence.jsonl").read_text()

    decide_result = runner.invoke(
        app,
        [
            "decide",
            "--workspace",
            str(workspace),
            "--room",
            room_id,
            "--decision",
            "Use expand-and-contract migration.",
            "--why",
            "It keeps rollback possible.",
            "--rejected",
            "direct rename",
            "--risk",
            "temporary complexity",
        ],
    )

    assert decide_result.exit_code == 0
    assert "expand-and-contract" in (room_path / "decisions.jsonl").read_text()

    report_result = runner.invoke(
        app,
        ["report", "--workspace", str(workspace), "--room", room_id],
    )

    assert report_result.exit_code == 0
    assert "Room Report" in report_result.stdout
    assert "expand-and-contract" in (room_path / "reports" / "final.md").read_text()

    list_result = runner.invoke(app, ["list", "--workspace", str(workspace)])

    assert list_result.exit_code == 0
    assert room_id in list_result.stdout
    assert "review_board" in list_result.stdout

    show_result = runner.invoke(
        app,
        ["show", "--workspace", str(workspace), "--room", room_id],
    )

    assert show_result.exit_code == 0
    assert "recent_decisions" in show_result.stdout
    assert "expand-and-contract" in show_result.stdout

    status_result = runner.invoke(
        app,
        ["status", "--workspace", str(workspace), "--room", room_id],
    )

    assert status_result.exit_code == 0
    assert "DISCUSSION" in status_result.stdout
    assert "review_board" in status_result.stdout

    close_result = runner.invoke(
        app,
        [
            "close",
            "--workspace",
            str(workspace),
            "--room",
            room_id,
            "--reason",
            "MVP flow is complete.",
        ],
    )

    assert close_result.exit_code == 0
    assert "closed room" in close_result.stdout
    assert '"status": "DONE"' in (room_path / "state.json").read_text()
    assert "MVP flow is complete." in (room_path / "transcript.jsonl").read_text()


def test_play_runs_two_codex_agents_with_fake_codex(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    args_log = tmp_path / "codex-args.log"
    fake_codex.write_text(
        f"""#!/bin/sh
printf "%s\\n" "$*" >> "{args_log}"
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
agent=$(printf "%s" "$prompt" | sed -n 's/.*participant `\\([^`]*\\)`.*/\\1/p' | head -n 1)
printf "fake response from %s\\nNext: continue.\\n" "$agent" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    result = runner.invoke(
        app,
        [
            "play",
            "--workspace",
            str(workspace),
            "--task",
            "Let two agents discuss the MVP shape.",
            "--rounds",
            "1",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert result.exit_code == 0
    assert "played 4 agent turns" in result.stdout
    room_id = next(part for part in result.stdout.split() if part.startswith("room_"))
    room_path = workspace / ".room" / "rooms" / room_id
    transcript = (room_path / "transcript.jsonl").read_text()
    participants = (room_path / "participants.json").read_text()
    assert "codex_agent_a" in participants
    assert "codex_agent_b" in participants
    assert "fake response from codex_agent_a" in transcript
    assert "fake response from codex_agent_b" in transcript
    assert "AGENT_DRAFT" in transcript
    assert "AGENT_REVIEW" in transcript
    assert "AGENT_REVISE" in transcript
    assert "AGENT_FINAL_CHECK" in transcript
    assert "fake response from codex_agent_a" in (room_path / "reports" / "final.md").read_text()
    assert "--model gpt-5.4" in args_log.read_text()


def test_parallel_opinion_pattern_keeps_two_turn_flow(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
agent=$(printf "%s" "$prompt" | sed -n 's/.*participant `\\([^`]*\\)`.*/\\1/p' | head -n 1)
step=$(printf "%s" "$prompt" | sed -n '/Your collaboration step:/{n;p;}' | head -n 1)
printf "parallel response from %s at %s\\nNext: continue.\\n" "$agent" "$step" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    result = runner.invoke(
        app,
        [
            "play",
            "--workspace",
            str(workspace),
            "--task",
            "Collect two independent opinions.",
            "--collaboration-pattern",
            "parallel_opinion",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert result.exit_code == 0
    assert "played 2 agent turns" in result.stdout
    room_id = next(part for part in result.stdout.split() if part.startswith("room_"))
    room_path = workspace / ".room" / "rooms" / room_id
    transcript = (room_path / "transcript.jsonl").read_text()
    state = json.loads((room_path / "state.json").read_text())
    assert state["collaboration_pattern"] == "parallel_opinion"
    assert "parallel response from codex_agent_a at opinion" in transcript
    assert "parallel response from codex_agent_b at opinion" in transcript


def test_play_runs_anthropic_api_runtime_without_logging_key(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    calls: list[dict[str, object]] = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(text="deepseek response\nNext: continue.")]
            )

    class FakeAnthropic:
        def __init__(self, **kwargs):
            calls.append({"client": kwargs})
            self.messages = FakeMessages()

    monkeypatch.setenv("FAKE_DEEPSEEK_KEY", "secret-value-that-must-not-be-written")
    monkeypatch.setitem(
        __import__("sys").modules,
        "anthropic",
        types.SimpleNamespace(Anthropic=FakeAnthropic),
    )

    result = runner.invoke(
        app,
        [
            "play",
            "--workspace",
            str(workspace),
            "--task",
            "Let two DeepSeek participants discuss the MVP shape.",
            "--collaboration-pattern",
            "parallel_opinion",
            "--runtime",
            "anthropic-api",
            "--model",
            "deepseek-v4-pro",
            "--anthropic-api-key-env",
            "FAKE_DEEPSEEK_KEY",
        ],
    )

    assert result.exit_code == 0
    assert "played 2 agent turns" in result.stdout
    room_id = next(part for part in result.stdout.split() if part.startswith("room_"))
    room_path = workspace / ".room" / "rooms" / room_id
    transcript = (room_path / "transcript.jsonl").read_text()
    assert "deepseek response" in transcript
    assert "secret-value-that-must-not-be-written" not in transcript
    assert calls[0]["client"]["api_key"] == "secret-value-that-must-not-be-written"
    assert calls[0]["client"]["base_url"] == "https://api.deepseek.com/anthropic"
    assert calls[1]["model"] == "deepseek-v4-pro"


def test_play_loads_workspace_env_for_anthropic_runtime(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace.joinpath(".env").write_text(
        "DEEPSEEK_API_KEY=secret-from-dotenv\n"
        "ROOM_ANTHROPIC_MODEL=deepseek-v4-pro\n"
    )
    calls: list[dict[str, object]] = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(content=[types.SimpleNamespace(text="dotenv response")])

    class FakeAnthropic:
        def __init__(self, **kwargs):
            calls.append({"client": kwargs})
            self.messages = FakeMessages()

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ROOM_ANTHROPIC_MODEL", raising=False)
    monkeypatch.setitem(
        __import__("sys").modules,
        "anthropic",
        types.SimpleNamespace(Anthropic=FakeAnthropic),
    )

    result = runner.invoke(
        app,
        [
            "play",
            "--workspace",
            str(workspace),
            "--task",
            "Use dotenv.",
            "--collaboration-pattern",
            "parallel_opinion",
            "--runtime",
            "anthropic-api",
        ],
    )

    assert result.exit_code == 0
    transcript = next((workspace / ".room" / "rooms").glob("room_*/transcript.jsonl")).read_text()
    assert "dotenv response" in transcript
    assert "secret-from-dotenv" not in transcript
    assert calls[0]["client"]["api_key"] == "secret-from-dotenv"
    assert calls[1]["model"] == "deepseek-v4-pro"


def test_play_runs_claude_cli_runtime_with_fake_claude(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_claude = tmp_path / "claude"
    args_log = tmp_path / "claude-args.log"
    fake_claude.write_text(
        f"""#!/bin/sh
printf "%s\\n" "$*" >> "{args_log}"
printf "fake claude response\\nNext: continue.\\n"
""",
    )
    fake_claude.chmod(0o755)

    result = runner.invoke(
        app,
        [
            "play",
            "--workspace",
            str(workspace),
            "--task",
            "Let two Claude participants discuss the MVP shape.",
            "--collaboration-pattern",
            "parallel_opinion",
            "--runtime",
            "claude-cli",
            "--claude-bin",
            str(fake_claude),
            "--model",
            "sonnet",
        ],
    )

    assert result.exit_code == 0
    assert "played 2 agent turns" in result.stdout
    room_id = next(part for part in result.stdout.split() if part.startswith("room_"))
    room_path = workspace / ".room" / "rooms" / room_id
    transcript = (room_path / "transcript.jsonl").read_text()
    assert "fake claude response" in transcript
    args = args_log.read_text()
    assert "--model sonnet" in args
    assert "--no-session-persistence" in args


def test_play_maps_claude_cli_to_deepseek_env_with_fake_claude(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    fake_claude = tmp_path / "claude"
    env_log = tmp_path / "claude-env.log"
    fake_claude.write_text(
        f"""#!/bin/sh
settings=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--settings" ]; then
    shift
    settings="$1"
  fi
  shift
done
printf "BASE=%s\\n" "$ANTHROPIC_BASE_URL" >> "{env_log}"
printf "AUTH=%s\\n" "${{ANTHROPIC_AUTH_TOKEN:+set}}" >> "{env_log}"
printf "API=%s\\n" "${{ANTHROPIC_API_KEY:+set}}" >> "{env_log}"
printf "MODEL=%s\\n" "$ANTHROPIC_MODEL" >> "{env_log}"
printf "SONNET=%s\\n" "$ANTHROPIC_DEFAULT_SONNET_MODEL" >> "{env_log}"
printf "HAIKU=%s\\n" "$ANTHROPIC_DEFAULT_HAIKU_MODEL" >> "{env_log}"
python3 - "$settings" >> "{env_log}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    env = json.load(f)["env"]
print("SETTINGS_BASE=" + env["ANTHROPIC_BASE_URL"])
print("SETTINGS_AUTH=" + ("set" if env["ANTHROPIC_AUTH_TOKEN"] else ""))
print("SETTINGS_SONNET=" + env["ANTHROPIC_DEFAULT_SONNET_MODEL"])
PY
printf "fake claude deepseek env response\\nNext: continue.\\n"
""",
    )
    fake_claude.chmod(0o755)
    monkeypatch.setenv("ROOM_CLAUDE_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-value-that-must-not-be-written")
    monkeypatch.setenv("ROOM_ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    monkeypatch.setenv("ROOM_ANTHROPIC_MODEL", "deepseek-v4-pro[1m]")
    monkeypatch.setenv("ROOM_CLAUDE_DEEPSEEK_MODEL", "deepseek-v4-flash")

    result = runner.invoke(
        app,
        [
            "play",
            "--workspace",
            str(workspace),
            "--task",
            "Route Claude Code through DeepSeek.",
            "--collaboration-pattern",
            "parallel_opinion",
            "--runtime",
            "claude-cli",
            "--claude-bin",
            str(fake_claude),
        ],
    )

    assert result.exit_code == 0
    env_text = env_log.read_text()
    assert "BASE=https://api.deepseek.com/anthropic" in env_text
    assert "AUTH=set" in env_text
    assert "API=set" in env_text
    assert "MODEL=deepseek-v4-flash" in env_text
    assert "SONNET=deepseek-v4-flash" in env_text
    assert "HAIKU=deepseek-v4-flash" in env_text
    assert "SETTINGS_BASE=https://api.deepseek.com/anthropic" in env_text
    assert "SETTINGS_AUTH=set" in env_text
    assert "SETTINGS_SONNET=deepseek-v4-flash" in env_text
    transcript = next((workspace / ".room" / "rooms").glob("room_*/transcript.jsonl")).read_text()
    assert "secret-value-that-must-not-be-written" not in transcript


def test_play_does_not_fallback_to_codex_when_requested_runtime_fails(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_claude = tmp_path / "claude"
    fake_codex = tmp_path / "codex"
    codex_args_log = tmp_path / "codex-args.log"
    fake_claude.write_text(
        """#!/bin/sh
printf "configured claude runtime failed intentionally\n" >&2
exit 7
""",
    )
    fake_codex.write_text(
        f"""#!/bin/sh
printf "%s\\n" "$*" >> "{codex_args_log}"
printf "unexpected codex fallback\\n"
""",
    )
    fake_claude.chmod(0o755)
    fake_codex.chmod(0o755)

    result = runner.invoke(
        app,
        [
            "play",
            "--workspace",
            str(workspace),
            "--task",
            "Do not silently swap runtimes.",
            "--collaboration-pattern",
            "parallel_opinion",
            "--runtime",
            "claude-cli",
            "--claude-bin",
            str(fake_claude),
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert result.exit_code != 0
    assert "claude -p failed" in result.output
    assert not codex_args_log.exists()
    rooms = list((workspace / ".room" / "rooms").glob("room_*/transcript.jsonl"))
    assert not rooms or "unexpected codex fallback" not in rooms[0].read_text()


def test_play_supports_mixed_participant_runtimes(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    fake_claude = tmp_path / "claude"
    codex_args_log = tmp_path / "codex-args.log"
    claude_args_log = tmp_path / "claude-args.log"
    fake_codex.write_text(
        f"""#!/bin/sh
printf "%s\\n" "$*" >> "{codex_args_log}"
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
printf "fake codex mixed response\\nNext: continue.\\n" > "$out"
""",
    )
    fake_claude.write_text(
        f"""#!/bin/sh
printf "%s\\n" "$*" >> "{claude_args_log}"
printf "fake claude mixed response\\nNext: continue.\\n"
""",
    )
    fake_codex.chmod(0o755)
    fake_claude.chmod(0o755)

    result = runner.invoke(
        app,
        [
            "play",
            "--workspace",
            str(workspace),
            "--task",
            "Mix Codex and Claude participants.",
            "--collaboration-pattern",
            "parallel_opinion",
            "--agent-a-runtime",
            "codex-cli",
            "--agent-b-runtime",
            "claude-cli",
            "--agent-a-bin",
            str(fake_codex),
            "--agent-b-bin",
            str(fake_claude),
            "--agent-a-model",
            "gpt-test",
            "--agent-b-model",
            "sonnet-test",
        ],
    )

    assert result.exit_code == 0
    assert "played 2 agent turns" in result.stdout
    room_id = next(part for part in result.stdout.split() if part.startswith("room_"))
    room_path = workspace / ".room" / "rooms" / room_id
    transcript = (room_path / "transcript.jsonl").read_text()
    assert "fake codex mixed response" in transcript
    assert "fake claude mixed response" in transcript
    assert "--model gpt-test" in codex_args_log.read_text()
    assert "--model sonnet-test" in claude_args_log.read_text()


def test_play_supports_mixed_codex_and_anthropic_participants(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    codex_args_log = tmp_path / "codex-args.log"
    calls: list[dict[str, object]] = []
    fake_codex.write_text(
        f"""#!/bin/sh
printf "%s\\n" "$*" >> "{codex_args_log}"
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
printf "fake codex plus api response\\nNext: continue.\\n" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(content=[types.SimpleNamespace(text="fake api response")])

    class FakeAnthropic:
        def __init__(self, **kwargs):
            calls.append({"client": kwargs})
            self.messages = FakeMessages()

    monkeypatch.setenv("FAKE_DEEPSEEK_KEY", "secret-value-that-must-not-be-written")
    monkeypatch.setitem(
        __import__("sys").modules,
        "anthropic",
        types.SimpleNamespace(Anthropic=FakeAnthropic),
    )

    result = runner.invoke(
        app,
        [
            "play",
            "--workspace",
            str(workspace),
            "--task",
            "Mix Codex and DeepSeek participants.",
            "--collaboration-pattern",
            "parallel_opinion",
            "--agent-a-runtime",
            "codex-cli",
            "--agent-b-runtime",
            "anthropic-api",
            "--agent-a-bin",
            str(fake_codex),
            "--agent-a-model",
            "gpt-test",
            "--agent-b-model",
            "deepseek-v4-pro",
            "--agent-b-api-base-url",
            "https://example.test/anthropic",
            "--anthropic-api-key-env",
            "FAKE_DEEPSEEK_KEY",
        ],
    )

    assert result.exit_code == 0
    room_id = next(part for part in result.stdout.split() if part.startswith("room_"))
    transcript = (workspace / ".room" / "rooms" / room_id / "transcript.jsonl").read_text()
    assert "fake codex plus api response" in transcript
    assert "fake api response" in transcript
    assert "secret-value-that-must-not-be-written" not in transcript
    assert "--model gpt-test" in codex_args_log.read_text()
    assert calls[0]["client"]["base_url"] == "https://example.test/anthropic"
    assert calls[1]["model"] == "deepseek-v4-pro"


def test_play_profile_loads_participant_roles_and_runtimes(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    fake_codex = tmp_path / "codex"
    codex_args_log = tmp_path / "codex-args.log"
    calls: list[dict[str, object]] = []
    workspace.joinpath(".room-profiles.toml").write_text(
        f"""
[profiles.advisory-mixed]
description = "Test mixed profile"
pattern = "parallel_opinion"
rounds = 1

[[profiles.advisory-mixed.participants]]
id = "codex_planner"
runtime = "codex-cli"
model = "gpt-profile"
role = "codebase planner"
authority = "primary"
weight = 1.0
can_block = true
bin = "{fake_codex}"
capabilities = {{ coding = 0.95 }}

[[profiles.advisory-mixed.participants]]
id = "deepseek_advisor"
runtime = "anthropic-api"
model = "deepseek-profile"
role = "lightweight product advisor"
authority = "advisory"
weight = 0.35
can_block = false
api_base_url = "https://profile.test/anthropic"
capabilities = {{ product = 0.75 }}
""",
    )
    fake_codex.write_text(
        f"""#!/bin/sh
printf "%s\\n" "$*" >> "{codex_args_log}"
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
printf "%s" "$prompt" > "{tmp_path / "codex-prompt.txt"}"
printf "profile codex response\\nNext: continue.\\n" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(text="profile api response")]
            )

    class FakeAnthropic:
        def __init__(self, **kwargs):
            calls.append({"client": kwargs})
            self.messages = FakeMessages()

    monkeypatch.setenv("FAKE_DEEPSEEK_KEY", "secret-value-that-must-not-be-written")
    monkeypatch.setitem(
        __import__("sys").modules,
        "anthropic",
        types.SimpleNamespace(Anthropic=FakeAnthropic),
    )

    result = runner.invoke(
        app,
        [
            "play",
            "--workspace",
            str(workspace),
            "--task",
            "Use a room profile.",
            "--profile",
            "advisory-mixed",
            "--anthropic-api-key-env",
            "FAKE_DEEPSEEK_KEY",
        ],
    )

    assert result.exit_code == 0
    room_id = next(part for part in result.stdout.split() if part.startswith("room_"))
    transcript = (workspace / ".room" / "rooms" / room_id / "transcript.jsonl").read_text()
    assert "codex_planner" in transcript
    assert "deepseek_advisor" in transcript
    assert "profile codex response" in transcript
    assert "profile api response" in transcript
    assert "--model gpt-profile" in codex_args_log.read_text()
    assert "role: codebase planner" in (tmp_path / "codex-prompt.txt").read_text()
    assert calls[0]["client"]["base_url"] == "https://profile.test/anthropic"
    assert calls[1]["model"] == "deepseek-profile"


def test_profile_loader_falls_back_to_bundled_profiles(tmp_path) -> None:
    profile = load_room_profile(tmp_path / "external-workspace", "advisory-mixed")

    assert profile.name == "advisory-mixed"
    assert profile.participants[0].id == "codex_planner"
    assert profile.participants[1].id == "deepseek_advisor"


def test_bundled_stage_profiles_are_available(tmp_path) -> None:
    workspace = tmp_path / "external-workspace"

    debug_profile = load_room_profile(workspace, "debug-recovery")
    final_profile = load_room_profile(workspace, "final-review")

    assert debug_profile.participants[0].id == "codex_debugger"
    assert debug_profile.participants[0].can_block is True
    assert debug_profile.participants[1].weight < debug_profile.participants[0].weight
    assert final_profile.participants[0].id == "claude_final_reviewer"
    assert final_profile.participants[0].runtime == "claude-cli"
    assert final_profile.participants[1].id == "deepseek_release_advisor"


def test_wake_captures_cycle_artifacts_with_fake_codex(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
agent=$(printf "%s" "$prompt" | sed -n 's/.*participant `\\([^`]*\\)`.*/\\1/p' | head -n 1)
printf "wake response from %s\\nNext: capture tasks.\\n" "$agent" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    result = runner.invoke(
        app,
        [
            "wake",
            "--workspace",
            str(workspace),
            "--task",
            "Build a durable room wake flow.",
            "--goal",
            "Design the next implementation slice.",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert result.exit_code == 0
    assert "cycle_001" in result.stdout
    room_id = next(part for part in result.stdout.split() if part.startswith("room_"))
    room_path = workspace / ".room" / "rooms" / room_id
    state = json.loads((room_path / "state.json").read_text())
    assert state["status"] == "OPEN_IDLE"
    assert state["collaboration_pattern"] == "draft_review_revise"
    assert "wake response from codex_agent_a" in (room_path / "transcript.jsonl").read_text()
    assert "wake response from codex_agent_b" in (room_path / "transcript.jsonl").read_text()
    assert (room_path / "cycles" / "cycle_001" / "prompt.md").exists()
    assert "Design the next implementation slice." in (
        room_path / "artifacts" / "room_summary.md"
    ).read_text()
    assert "Collaboration pattern: draft_review_revise" in (
        room_path / "artifacts" / "room_summary.md"
    ).read_text()
    assert "wake response from codex_agent_a" in (
        room_path / "artifacts" / "design.md"
    ).read_text()
    assert "pass/fail checks" in (room_path / "artifacts" / "tasks.md").read_text()
    checkpoint = (room_path / "artifacts" / "wake_checkpoint.json").read_text()
    assert '"resume_status": "authoritative"' in checkpoint
    assert '"source_cycle": "cycle_001"' in checkpoint
    assert (room_path / "cycles" / "cycle_001" / "wake_checkpoint.json").exists()
    execution_plan = (room_path / "artifacts" / "execution_plan.json").read_text()
    assert '"recommended_action": "implement"' in execution_plan
    assert '"requires_user_approval": false' in execution_plan
    assert (room_path / "cycles" / "cycle_001" / "execution_plan.json").exists()
    reference = json.loads((room_path / "artifacts" / "main_agent_reference.json").read_text())
    assert reference["source_cycle"] == "cycle_001"
    assert reference["advisory_only"] is True
    assert reference["recommended_focus"]
    assert (room_path / "cycles" / "cycle_001" / "main_agent_reference.json").exists()
    synthesis = json.loads((room_path / "artifacts" / "room_synthesis.json").read_text())
    approval = json.loads((room_path / "artifacts" / "approval_state.json").read_text())
    assert synthesis["source_cycle"] == "cycle_001"
    assert synthesis["approval_required"] is False
    assert approval["status"] == "not_required"
    assert approval["synthesis_id"] == synthesis["synthesis_id"]
    assert (room_path / "cycles" / "cycle_001" / "room_synthesis.json").exists()
    assert (room_path / "cycles" / "cycle_001" / "approval_state.json").exists()

    second_result = runner.invoke(
        app,
        [
            "wake",
            "--workspace",
            str(workspace),
            "--room",
            room_id,
            "--goal",
            "Use the checkpoint to continue.",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert second_result.exit_code == 0
    assert "cycle_002" in second_result.stdout
    cycle_002_prompt = (room_path / "cycles" / "cycle_002" / "prompt.md").read_text()
    assert "wake_checkpoint.json" in cycle_002_prompt
    assert "source_cycle: cycle_001" in cycle_002_prompt
    assert '"source_cycle": "cycle_002"' in (
        room_path / "artifacts" / "wake_checkpoint.json"
    ).read_text()


def test_observer_payload_reads_discussion_and_artifacts(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
agent=$(printf "%s" "$prompt" | sed -n 's/.*participant `\\([^`]*\\)`.*/\\1/p' | head -n 1)
printf "observer response from %s\\nRecommendation: show the room live.\\n" "$agent" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    result = runner.invoke(
        app,
        [
            "wake",
            "--workspace",
            str(workspace),
            "--task",
            "Design a read-only room observer service.",
            "--goal",
            "Show room discussion and result artifacts.",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert result.exit_code == 0
    room_id = next(part for part in result.stdout.split() if part.startswith("room_"))
    payload = build_room_payload(workspace, room_id)
    artifacts = payload["artifacts"]
    transcript = "\n".join(turn["content"] for turn in payload["recent_transcript"])
    assert "observer response from codex_agent_a" in transcript
    assert "main_agent_reference.json" in artifacts
    assert artifacts["main_agent_reference.json"]["content"]["advisory_only"] is True
    assert "design.md" in artifacts


def test_observer_http_endpoints_return_rooms_and_artifacts(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    init_result = runner.invoke(
        app,
        ["init", "--workspace", str(workspace), "--task", "Observer HTTP smoke"],
    )
    assert init_result.exit_code == 0
    room_id = next(part for part in init_result.stdout.split() if part.startswith("room_"))

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(workspace))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        rooms = json.loads(urlopen(f"{base_url}/api/rooms", timeout=5).read())
        room = json.loads(urlopen(f"{base_url}/api/rooms/{room_id}", timeout=5).read())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert rooms["workspace"] == str(workspace.resolve())
    assert any(item["room_id"] == room_id for item in rooms["rooms"])
    assert room["state"]["room_id"] == room_id
    assert room["artifacts"] == {}


def test_observer_room_list_handles_legacy_and_invalid_room_state(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    legacy_result = runner.invoke(
        app,
        ["init", "--workspace", str(workspace), "--task", "Legacy observer room"],
    )
    valid_result = runner.invoke(
        app,
        ["init", "--workspace", str(workspace), "--task", "Valid observer room"],
    )
    assert legacy_result.exit_code == 0
    assert valid_result.exit_code == 0
    legacy_id = next(part for part in legacy_result.stdout.split() if part.startswith("room_"))
    valid_id = next(part for part in valid_result.stdout.split() if part.startswith("room_"))

    legacy_state = workspace / ".room" / "rooms" / legacy_id / "state.json"
    legacy_payload = json.loads(legacy_state.read_text())
    legacy_payload["collaboration_pattern"] = "mixed_runtime_review"
    legacy_state.write_text(json.dumps(legacy_payload))

    invalid_dir = workspace / ".room" / "rooms" / "room_invalid"
    invalid_dir.mkdir(parents=True)
    invalid_dir.joinpath("state.json").write_text('{"collaboration_pattern": "future_pattern"}')

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(workspace))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        rooms = json.loads(urlopen(f"{base_url}/api/rooms", timeout=5).read())
        legacy_room = json.loads(urlopen(f"{base_url}/api/rooms/{legacy_id}", timeout=5).read())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    room_ids = {item["room_id"] for item in rooms["rooms"]}
    assert legacy_id in room_ids
    assert valid_id in room_ids
    assert "room_invalid" not in room_ids
    assert legacy_room["state"]["collaboration_pattern"] == "mixed_runtime_review"


def test_observer_handles_malformed_json_artifact_as_text(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    init_result = runner.invoke(
        app,
        ["init", "--workspace", str(workspace), "--task", "Malformed artifact smoke"],
    )
    assert init_result.exit_code == 0
    room_id = next(part for part in init_result.stdout.split() if part.startswith("room_"))
    room_path = workspace / ".room" / "rooms" / room_id
    artifact_path = room_path / "artifacts" / "main_agent_reference.json"
    artifact_path.write_text("{not valid json")

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(workspace))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        room = json.loads(urlopen(f"{base_url}/api/rooms/{room_id}", timeout=5).read())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    artifact = room["artifacts"]["main_agent_reference.json"]
    assert artifact["kind"] == "text"
    assert artifact["content"] == "{not valid json"


def test_ask_keeps_simple_task_solo(tmp_path) -> None:
    workspace = tmp_path / "workspace"

    result = runner.invoke(
        app,
        [
            "ask",
            "--workspace",
            str(workspace),
            "--task",
            "Rename a local variable.",
        ],
    )

    assert result.exit_code == 0
    assert "action: solo" in result.stdout
    room_id = next(part for part in result.stdout.split() if part.startswith("room_"))
    room_path = workspace / ".room" / "rooms" / room_id
    assert '"status": "OPEN_IDLE"' in (room_path / "state.json").read_text()
    assert not (room_path / "artifacts" / "wake_checkpoint.json").exists()


def test_ask_wakes_for_complex_task_with_fake_codex(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
agent=$(printf "%s" "$prompt" | sed -n 's/.*participant `\\([^`]*\\)`.*/\\1/p' | head -n 1)
printf "ask response from %s\\nNext: write design.\\n" "$agent" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    result = runner.invoke(
        app,
        [
            "ask",
            "--workspace",
            str(workspace),
            "--task",
            "Design an architecture migration with rollback risk.",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert result.exit_code == 0
    assert "action: wake" in result.stdout
    assert "cycle_001" in result.stdout
    assert "ask response from codex_agent_a" in result.stdout
    room_id = next(part for part in result.stdout.split() if part.startswith("room_"))
    room_path = workspace / ".room" / "rooms" / room_id
    assert "ask response from codex_agent_a" in (room_path / "transcript.jsonl").read_text()
    assert (room_path / "artifacts" / "wake_checkpoint.json").exists()
    assert (room_path / "artifacts" / "execution_plan.json").exists()
    assert (room_path / "artifacts" / "main_agent_reference.json").exists()
    assert (room_path / "artifacts" / "room_synthesis.json").exists()
    assert (room_path / "artifacts" / "approval_state.json").exists()


def test_ask_existing_room_triages_new_task_with_fake_codex(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
agent=$(printf "%s" "$prompt" | sed -n 's/.*participant `\\([^`]*\\)`.*/\\1/p' | head -n 1)
printf "existing room ask from %s\\nNext: continue.\\n" "$agent" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    first = runner.invoke(
        app,
        [
            "ask",
            "--workspace",
            str(workspace),
            "--task",
            "Rename a local variable.",
        ],
    )

    assert first.exit_code == 0
    assert "action: solo" in first.stdout
    room_id = next(part for part in first.stdout.split() if part.startswith("room_"))

    second = runner.invoke(
        app,
        [
            "ask",
            "--workspace",
            str(workspace),
            "--room",
            room_id,
            "--task",
            "Design an architecture migration with rollback risk.",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert second.exit_code == 0
    assert "action: wake" in second.stdout
    room_path = workspace / ".room" / "rooms" / room_id
    assert "New ask: Design an architecture migration" in (
        room_path / "transcript.jsonl"
    ).read_text()
    assert "existing room ask from codex_agent_a" in second.stdout


def test_ask_json_output_includes_design_and_tasks(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
agent=$(printf "%s" "$prompt" | sed -n 's/.*participant `\\([^`]*\\)`.*/\\1/p' | head -n 1)
printf "json ask from %s\\nNext: continue.\\n" "$agent" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    result = runner.invoke(
        app,
        [
            "ask",
            "--workspace",
            str(workspace),
            "--task",
            "Design an architecture migration with rollback risk.",
            "--codex-bin",
            str(fake_codex),
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert '"action": "wake"' in result.stdout
    assert '"cycle_id": "cycle_001"' in result.stdout
    assert '"design"' in result.stdout
    assert '"main_agent_reference"' in result.stdout
    assert '"execution_plan"' in result.stdout
    assert '"room_synthesis"' in result.stdout
    assert '"approval_state"' in result.stdout
    assert '"status": "not_required"' in result.stdout
    assert '"recommended_action": "implement"' in result.stdout
    assert "json ask from codex_agent_a" in result.stdout


def test_host_ask_keeps_simple_task_solo(tmp_path) -> None:
    workspace = tmp_path / "workspace"

    result = runner.invoke(
        app,
        [
            "host-ask",
            "--workspace",
            str(workspace),
            "--task",
            "Rename a local variable.",
        ],
    )

    assert result.exit_code == 0
    assert '"action": "solo"' in result.stdout
    assert '"host_decision"' in result.stdout
    assert '"next_step": "continue_solo"' in result.stdout
    assert '"requires_user_approval": false' in result.stdout
    payload = json.loads(result.stdout)
    room_id = payload["room_id"]
    room_path = workspace / ".room" / "rooms" / room_id
    assert (room_path / "artifacts" / "host_decision.json").exists()


def test_host_ask_wakes_and_returns_approval_gate(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
agent=$(printf "%s" "$prompt" | sed -n 's/.*participant `\\([^`]*\\)`.*/\\1/p' | head -n 1)
printf "host ask response from %s\\nNext: ask for approval.\\n" "$agent" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    result = runner.invoke(
        app,
        [
            "host-ask",
            "--workspace",
            str(workspace),
            "--task",
            "Design an architecture migration with rollback risk.",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert result.exit_code == 0
    assert '"action": "wake"' in result.stdout
    assert '"execution_plan"' in result.stdout
    assert '"room_synthesis"' in result.stdout
    assert '"approval_state"' in result.stdout
    assert '"host_decision"' in result.stdout
    assert '"next_step": "execute"' in result.stdout
    assert '"recommended_action": "implement"' in result.stdout
    assert '"requires_user_approval": false' in result.stdout
    assert '"main_agent_reference"' in result.stdout
    assert "host ask response from codex_agent_a" in result.stdout


def test_codex_ask_simple_task_returns_main_session_workflow(tmp_path) -> None:
    workspace = tmp_path / "workspace"

    result = runner.invoke(
        app,
        [
            "codex-ask",
            "--workspace",
            str(workspace),
            "--task",
            "Rename a local variable.",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["action"] == "solo"
    assert payload["host_decision"]["next_step"] == "continue_solo"
    assert payload["codex_workflow"]["codex_action"] == "continue_main_session"
    assert payload["codex_workflow"]["next_step"] == "continue_solo"


def test_codex_ask_complex_task_returns_approval_workflow(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
agent=$(printf "%s" "$prompt" | sed -n 's/.*participant `\\([^`]*\\)`.*/\\1/p' | head -n 1)
printf "codex workflow response from %s\\nNext: ask for approval.\\n" "$agent" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    result = runner.invoke(
        app,
        [
            "codex-ask",
            "--workspace",
            str(workspace),
            "--task",
            "Design an architecture migration with rollback risk.",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["action"] == "wake"
    assert payload["host_decision"]["next_step"] == "execute"
    assert payload["approval_state"]["status"] == "not_required"
    assert payload["room_synthesis"]["approval_required"] is False
    assert payload["main_agent_reference"]["advisory_only"] is True
    assert payload["codex_workflow"]["codex_action"] == "execute_with_room_reference"
    assert payload["codex_workflow"]["advisory_only"] is True
    assert payload["codex_workflow"]["reference_path"].endswith("main_agent_reference.json")
    assert "codex workflow response from codex_agent_a" in payload["design"]

    reference_result = runner.invoke(
        app,
        ["reference-context", "--workspace", str(workspace), "--room", payload["room_id"]],
    )

    assert reference_result.exit_code == 0
    reference = json.loads(reference_result.stdout)
    assert reference["reference_id"].endswith("_main_agent_reference")
    assert reference["advisory_only"] is True
    assert reference["recommended_focus"]


def test_accept_plan_enables_execution_context(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
agent=$(printf "%s" "$prompt" | sed -n 's/.*participant `\\([^`]*\\)`.*/\\1/p' | head -n 1)
printf "accept flow response from %s\\nNext: accept plan.\\n" "$agent" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    ask_result = runner.invoke(
        app,
        [
            "codex-ask",
            "--workspace",
            str(workspace),
            "--task",
            "Design an architecture migration with rollback risk.",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert ask_result.exit_code == 0
    payload = json.loads(ask_result.stdout)
    room_id = payload["room_id"]

    pending_context = runner.invoke(
        app,
        ["execution-context", "--workspace", str(workspace), "--room", room_id],
    )

    assert pending_context.exit_code != 0

    accept_result = runner.invoke(
        app,
        [
            "accept-plan",
            "--workspace",
            str(workspace),
            "--room",
            room_id,
            "--reason",
            "Looks good.",
            "--task-id",
            "task_001",
            "--task-id",
            "task_003",
        ],
    )

    assert accept_result.exit_code == 0
    approval = json.loads(accept_result.stdout)
    assert approval["status"] == "accepted"
    assert approval["accepted_task_ids"] == ["task_001", "task_003"]
    assert approval["rejected_task_ids"] == ["task_002"]

    context_result = runner.invoke(
        app,
        ["execution-context", "--workspace", str(workspace), "--room", room_id],
    )

    assert context_result.exit_code == 0
    context = json.loads(context_result.stdout)
    assert context["room_id"] == room_id
    assert context["synthesis_id"] == approval["synthesis_id"]
    assert context["accepted_task_ids"] == ["task_001", "task_003"]
    assert "room_synthesis.json" in context["artifact_pointers"]
    execution_context_path = (
        workspace / ".room" / "rooms" / room_id / "artifacts" / "execution_context.json"
    )
    assert execution_context_path.exists()

    resume_result = runner.invoke(
        app,
        [
            "codex-ask",
            "--workspace",
            str(workspace),
            "--room",
            room_id,
            "--task",
            "Continue accepted implementation.",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert resume_result.exit_code == 0
    resume_payload = json.loads(resume_result.stdout)
    assert resume_payload["action"] == "accepted"
    assert resume_payload["host_decision"]["next_step"] == "execute"
    assert resume_payload["codex_workflow"]["codex_action"] == "execute_accepted_plan"
    assert resume_payload["codex_workflow"]["execution_context_path"].endswith(
        "execution_context.json"
    )
    assert resume_payload["execution_context"]["accepted_task_ids"] == ["task_001", "task_003"]


def test_reject_plan_blocks_execution_context(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
agent=$(printf "%s" "$prompt" | sed -n 's/.*participant `\\([^`]*\\)`.*/\\1/p' | head -n 1)
printf "reject flow response from %s\\nNext: reject plan.\\n" "$agent" > "$out"
""",
    )
    fake_codex.chmod(0o755)

    ask_result = runner.invoke(
        app,
        [
            "codex-ask",
            "--workspace",
            str(workspace),
            "--task",
            "Design an architecture migration with rollback risk.",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert ask_result.exit_code == 0
    room_id = json.loads(ask_result.stdout)["room_id"]

    reject_result = runner.invoke(
        app,
        [
            "reject-plan",
            "--workspace",
            str(workspace),
            "--room",
            room_id,
            "--reason",
            "Needs another option.",
        ],
    )

    assert reject_result.exit_code == 0
    approval = json.loads(reject_result.stdout)
    assert approval["status"] == "rejected"
    assert approval["reason"] == "Needs another option."

    context_result = runner.invoke(
        app,
        ["execution-context", "--workspace", str(workspace), "--room", room_id],
    )

    assert context_result.exit_code != 0


def test_synthesis_extracts_actionable_agent_details(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    out="$1"
  fi
  shift
done
prompt=$(cat)
agent=$(printf "%s" "$prompt" | sed -n 's/.*participant `\\([^`]*\\)`.*/\\1/p' | head -n 1)
cat > "$out" <<EOF
${agent}: Decision recommendation
Use finish-execution as the only writer for execution_result.json.
- execution_id ties the result to execution_context.
- status must be succeeded | failed | cancelled.
- source_context hash should prevent stale completion.
- repeated finish with identical payload is idempotent.
- repeated finish with different payload is a hard conflict.
Acceptance criteria:
- downstream reader can reconstruct outcome from execution_result.json.
EOF
""",
    )
    fake_codex.chmod(0o755)

    result = runner.invoke(
        app,
        [
            "codex-ask",
            "--workspace",
            str(workspace),
            "--task",
            "Design execution_result.json and finish-execution command.",
            "--codex-bin",
            str(fake_codex),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    synthesis = payload["room_synthesis"]
    assert "finish-execution" in synthesis["recommended_path"]
    assert "execution_id" in synthesis["recommended_path"]
    assert "source_context" in synthesis["recommended_path"]
    assert "hard conflict" in synthesis["recommended_path"]
    task_acceptance = "\n".join(
        acceptance for task in synthesis["tasks"] for acceptance in task["acceptance"]
    )
    assert "execution_id" in task_acceptance
    assert "downstream reader" in task_acceptance

    accept_result = runner.invoke(
        app,
        [
            "accept-plan",
            "--workspace",
            str(workspace),
            "--room",
            payload["room_id"],
        ],
    )
    assert accept_result.exit_code == 0

    context_result = runner.invoke(
        app,
        ["execution-context", "--workspace", str(workspace), "--room", payload["room_id"]],
    )
    assert context_result.exit_code == 0
    context = json.loads(context_result.stdout)
    assert "finish-execution" in context["implementation_brief"]
    assert any("execution_id" in item for item in context["verification"])
