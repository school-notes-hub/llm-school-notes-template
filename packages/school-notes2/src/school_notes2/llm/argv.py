"""The fixed `podman run` argv of plan 7.4 and the harness command of a role template."""

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from ..config import Harness, Role

# Defaults only: the configuration (Config.provider_domains / login_domains) is the source.
DEFAULT_PROVIDER_DOMAINS = ("api.anthropic.com", "api.openai.com", "auth.openai.com",
                            "chatgpt.com")
DEFAULT_LOGIN_DOMAINS = ("claude.ai", "platform.claude.com", "console.anthropic.com")
# The entrypoint's own exit codes; high values so a harness's own 10/11/12 cannot pass for them.
EXIT_PREFLIGHT, EXIT_API, EXIT_FIREWALL = 210, 211, 212
PODMAN_FAILED = 125            # podman itself could not create or start the container
NOT_EXECUTABLE = (126, 127)    # the template's command is missing in the image
ROLES = ("writer", "reviewer")
# The preflight probes the API of the harness that will run, not just any provider.
HARNESS_API = {"codex": "api.openai.com", "claude": "api.anthropic.com"}
LOGIN_COMMANDS = {"codex": ["codex", "login", "--device-auth"], "claude": ["claude"]}
PLACEHOLDER = re.compile(r"\{(model|effort)\}")
OUTPUT_INSTRUCTION = {
    "file": ("A választ a `/out/review.json` fájlba írd egyetlen JSON-objektumként: "
             "`verdict` (ok | changes), `findings` [{id: R1…, file, line, problem, suggestion, relates_to, new_evidence?}], "
             "`figures` [{file, page, verdict, checks, observed, description}], "
             "`responses` [{key, verdict: accept | keep, answer}], `owner_notes` [szöveg]."),
    "stdout": ("A válaszod végén írd ki a review-t egyetlen JSON-objektumként: "
               "`verdict` (ok | changes), `findings` [{id: R1…, file, line, problem, suggestion, relates_to, new_evidence?}], "
               "`figures` [{file, page, verdict, checks, observed, description}], "
               "`responses` [{key, verdict: accept | keep, answer}], `owner_notes` [szöveg]."),
}


def container_name(learner: str, suffix: str = "") -> str:
    return f"school-notes-{learner}{suffix}"


def home_volume(learner: str, role: str) -> str:
    """One harness home per learner AND role: the writer can never plant settings, hooks or
    instructions that the nightly reviewer would load (its session history stays apart too)."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    return f"sn-agent-home-{learner}-{role}"


def family(harness: Harness) -> str:
    """codex | claude: the template name without its variant suffix (claude-review → claude)."""
    return harness.name.split("-")[0]


def api_domain(harness: Harness, allowed: tuple[str, ...]) -> str:
    return HARNESS_API.get(family(harness), allowed[0])


def prompt(role_name: str, output_mode: str = "file") -> str:
    """The fixed prompt of a role, byte-identical on every call (K12)."""
    if role_name not in (*ROLES, "fix"):
        raise ValueError(f"unknown prompt {role_name!r}")
    name = role_name
    text = resources.files(__package__).joinpath("prompts", f"{name}.txt").read_text("utf-8")
    return text.replace("{output_instruction}", OUTPUT_INSTRUCTION[output_mode])


def expand(template: list[str], role: Role) -> list[str]:
    """Fill {model} and {effort}; every other brace (JSON in an argument) stays as it is."""
    values = {"model": role.model, "effort": role.effort}
    return [PLACEHOLDER.sub(lambda m: values[m.group(1)], part) for part in template]


def harness_command(harness: Harness, role: Role, text: str) -> list[str]:
    """The headless command; the prompt goes last in argv when the template wants no stdin."""
    argv = expand(harness.headless, role)
    return argv if harness.prompt_stdin else argv + [text]


@dataclass(frozen=True)
class Mounts:
    work: Path | None = None
    work_readonly: bool = False
    sessdir: Path | None = None      # holds mcp.sock; absent for the reviewer
    in_dir: Path | None = None
    out_dir: Path | None = None
    home: bool = True                # the role's harness-home volume


@dataclass(frozen=True)
class Limits:
    """Container resources (the VM has 3.8 GiB and no swap); None leaves a limit out."""

    pids: int | None = 512
    memory: str | None = "2g"
    init: bool = True


def podman_argv(*, learner: str, image: str, run_id: str, mounts: Mounts, name: str,
                role: str = "writer", interactive: bool = False, network: bool = True,
                allowed_domains: tuple[str, ...] = DEFAULT_PROVIDER_DOMAINS,
                probe_domain: str | None = None, limits: Limits = Limits(),
                podman: str = "podman") -> list[str]:
    """The fixed `podman run` argv of plan 7.4, without the harness command."""
    argv = [podman, "run", "--rm", "--name", name, "--userns=keep-id", "--user", "0",
            "--security-opt", "no-new-privileges", "--ulimit", "core=0", "--tmpfs", "/tmp"]
    argv += _limits(limits)
    argv += ["--cap-add=NET_ADMIN,NET_RAW"] if network else ["--network", "none"]
    argv += _volumes(learner, role, mounts)
    argv += ["-e", f"SN_RUN_ID={run_id}"]
    if network:
        probe = probe_domain or allowed_domains[0]
        argv += ["-e", f"SN_ALLOWED_DOMAINS={','.join(allowed_domains)}",
                 "-e", f"SN_MODEL_PROBE=https://{probe}/"]
    else:
        argv += ["-e", "SN_NO_NETWORK=1"]
    argv += ["-it"] if interactive else ["-i"]
    return argv + [image]


def _limits(limits: Limits) -> list[str]:
    out = []
    if limits.init:
        out.append("--init")
    if limits.pids:
        out.append(f"--pids-limit={limits.pids}")
    if limits.memory:
        out.append(f"--memory={limits.memory}")
    return out


def _volumes(learner: str, role: str, mounts: Mounts) -> list[str]:
    out = []
    if mounts.work:
        out += ["-v", f"{mounts.work}:/work:{'ro' if mounts.work_readonly else 'rw'}"]
    if mounts.in_dir:
        out += ["-v", f"{mounts.in_dir}:/in:ro"]
    if mounts.out_dir:
        out += ["-v", f"{mounts.out_dir}:/out:rw"]
    if mounts.home:
        out += ["-v", f"{home_volume(learner, role)}:/home/agent"]
    if mounts.sessdir:
        # Read-only: connecting to the socket still works, but the container cannot fill
        # the host's runtime tmpfs or plant files beside the socket.
        out += ["-v", f"{mounts.sessdir}:/run/sn:ro"]
    return out
