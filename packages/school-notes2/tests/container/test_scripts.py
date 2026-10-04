import os
import shutil
import subprocess
from importlib import resources

import pytest

DIR = resources.files("school_notes2").joinpath("container")
SCRIPTS = ("entrypoint.sh", "init-firewall.sh", "sn-preflight", "clean-home.sh")


@pytest.mark.parametrize("name", SCRIPTS)
def test_scripts_parse(name):
    assert subprocess.run(["bash", "-n", str(DIR / name)]).returncode == 0


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not installed")
@pytest.mark.parametrize("name", SCRIPTS)
def test_shellcheck(name):
    assert subprocess.run(["shellcheck", "-S", "warning", str(DIR / name)]).returncode == 0


@pytest.mark.skipif(os.getuid() == 0, reason="needs a non-root user")
def test_entrypoint_refuses_to_run_as_non_root():
    proc = subprocess.run(["bash", str(DIR / "entrypoint.sh"), "true"], capture_output=True)
    assert proc.returncode == 212


def test_firewall_without_domains_fails_with_212():
    env = {"PATH": os.environ["PATH"]}
    proc = subprocess.run(["bash", str(DIR / "init-firewall.sh")], env=env, capture_output=True)
    assert proc.returncode == 212


def test_firewall_opens_dns_only_to_the_resolvers():
    text = (DIR / "init-firewall.sh").read_text()
    assert "/etc/resolv.conf" in text and '-d "$ns" -p udp --dport 53' in text
    assert "--dport 53 -j ACCEPT" not in text.replace('-d "$ns" -p udp --dport 53 -j ACCEPT', "") \
        .replace('-d "$ns" -p tcp --dport 53 -j ACCEPT', "")


def test_preflight_probes_dns_over_tcp_and_planted_config():
    text = (DIR / "sn-preflight").read_text()
    assert "/dev/tcp/$candidate/53" in text and ".claude/settings.json" in text
    assert "/work/.git" in text and "/work/.ssh" in text


def test_clean_home_keeps_login_and_removes_planted_config(tmp_path):
    home = tmp_path / "home"
    keep = [".claude/.credentials.json", ".codex/auth.json", ".claude/projects/x/s.jsonl"]
    drop = [".claude/settings.json", ".claude/hooks/stop.sh", ".claude/CLAUDE.md",
            ".codex/AGENTS.md", ".codex/config.toml", ".bashrc", ".config/x"]
    for rel in keep + drop:
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text("x")
    (home / ".claude.json").write_text('{"oauthAccount": {"a": 1}, "mcpServers": {"x": {}}, '
                                       '"projects": {"/work": {"mcpServers": {"y": {}}, "k": 1}}}')
    script = (DIR / "clean-home.sh").read_text().replace("home=/home/agent", f"home={home}")
    assert subprocess.run(["bash", "-c", script]).returncode == 0
    for rel in keep:
        assert (home / rel).exists(), rel
    for rel in drop:
        assert not (home / rel).exists(), rel
    import json
    state = json.loads((home / ".claude.json").read_text())
    assert state == {"oauthAccount": {"a": 1}, "projects": {"/work": {"k": 1}}}


def test_clean_home_removes_project_memory_and_codex_memories(tmp_path):
    """Verification review 3.8: per-project memory/settings would carry instructions over."""
    home = tmp_path / "home"
    keep = [".claude/projects/-work/session.jsonl", ".claude/.credentials.json"]
    drop = [".claude/projects/-work/memory/MEMORY.md", ".claude/projects/-work/settings.json",
            ".claude/projects/-work/settings.local.json", ".claude/projects/-work/CLAUDE.md",
            ".claude/projects/-work/x/AGENTS.md", ".codex/memories/notes.md",
            ".codex/sessions/AGENTS.md"]
    for rel in keep + drop:
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text("x")
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "MEMORY.md").write_text("keep me")
    (home / ".claude/projects/-other").mkdir()
    (home / ".claude/projects/-other/memory").symlink_to(victim)
    script = (DIR / "clean-home.sh").read_text().replace("home=/home/agent", f"home={home}")
    assert subprocess.run(["bash", "-c", script]).returncode == 0
    for rel in keep:
        assert (home / rel).exists(), rel
    for rel in drop:
        assert not (home / rel).exists(), rel
    assert (victim / "MEMORY.md").exists()
    assert not (home / ".claude/projects/-other/memory").is_symlink()   # the link itself goes


def test_clean_home_removes_a_symlinked_config_dir_without_following(tmp_path):
    home, target = tmp_path / "home", tmp_path / "victim"
    target.mkdir()
    (target / "settings.json").write_text("keep me")
    home.mkdir()
    (home / ".claude").symlink_to(target)
    script = (DIR / "clean-home.sh").read_text().replace("home=/home/agent", f"home={home}")
    assert subprocess.run(["bash", "-c", script]).returncode == 0
    assert not (home / ".claude").exists() and (target / "settings.json").exists()


def test_containerfile_pins_base_and_versions():
    text = (DIR / "Containerfile").read_text()
    assert "node:24-trixie-slim@sha256:" in text
    assert "CLAUDE_CODE_VERSION=2.1.288" in text and "CODEX_VERSION=0.160.0" in text
    for tool in ("ripgrep", "socat", "iptables", "librsvg2-bin", "graphviz"):
        assert tool in text
    assert "sn-clean-home" in text
    assert "ENTRYPOINT" in text and "UV_OFFLINE=1" in text


def test_preflight_env_allowlist_matches_launcher():
    text = (DIR / "sn-preflight").read_text()
    for key in ("SN_RUN_ID", "SN_ALLOWED_DOMAINS", "SN_MODEL_PROBE", "SN_NO_NETWORK", "CLAUDE_CODE_VERSION"):
        assert f" {key} " in text
    assert "SSH_AUTH_SOCK" in text and "example.com" in text


def test_build_time_claude_version_survives_clean_environment():
    text = (DIR / "Containerfile").read_text().split("ENV SN_AGENT_UID=", 1)[1]
    assert "CLAUDE_CODE_VERSION=${CLAUDE_CODE_VERSION}" in text
    script = (DIR / "entrypoint.sh").read_text().split("keep=(", 1)[1].split("\ncd /work", 1)[0]
    proc = subprocess.run(["bash", "-c", 'keep=(' + script + '\nenv -i "${keep[@]}" /usr/bin/env'],
                          env={"CLAUDE_CODE_VERSION": "2.1.7"}, capture_output=True, text=True, check=True)
    assert "CLAUDE_CODE_VERSION=2.1.7" in proc.stdout.splitlines()
