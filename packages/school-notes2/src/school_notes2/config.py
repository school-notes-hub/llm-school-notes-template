"""The tool's configuration (local pipeline plan 3.1): `~/.config/school-notes/config.toml`, no
secrets (the keys are in the ops repo's `.env`).

    root = "~/.local/share/school-notes"     # state, logs, site clones, downloads
    browser = "…/chrome"                       # optional: the site build's browser check
    [git]            name, email               # the tool's commits
    [students.<t>]   drive_root, grade, site_repo, local_repo (optional)
    [limits]         image_monthly_usd, image_reservation_usd, image_year_total_usd, image_year_learner_usd
    [sources]        max_side_px, jpeg_quality, pdf_dpi
    [timeouts]       per external call, seconds

A key the tool no longer reads (from the VM era: `[roles.*]`, `email_to`, `secrets_dir`,
`ssh_hostname`, `repo_key`, `ready_after_s`, …) is ignored with one warning line; it never stops
a command."""

import re
import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DEFAULT_PATH = Path("~/.config/school-notes/config.toml").expanduser()


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Student:
    name: str
    site_repo: str       # address of the public site repo (gh-pages); pushed over HTTPS only
    drive_root: str      # Drive folder id of `Tanulási anyagok/<Tanuló>`
    grade: int           # school year
    local_repo: Path | None = None   # the owner's working copy; default ~/jegyzet/school-notes-<name>-active


@dataclass(frozen=True)
class Timeouts:
    drive_call_s: int = 300
    download_package_s: int = 1200
    ls_remote_s: int = 60
    fetch_s: int = 600
    push_s: int = 900
    image_generate_s: int = 600
    build_s: int = 1800
    browser_check_s: int = 900
    check_public_s: int = 300


@dataclass(frozen=True)
class Sources:
    max_side_px: int = 2000
    jpeg_quality: int = 85
    pdf_dpi: int = 200


@dataclass(frozen=True)
class Limits:
    image_monthly_usd: float = 10.0
    image_reservation_usd: float = 0.05
    image_year_total_usd: float = 120.0     # safety cap: twelve monthly caps
    image_year_learner_usd: float = 120.0


@dataclass(frozen=True)
class Config:
    root: Path
    git_name: str
    git_email: str
    students: dict[str, Student]
    timeouts: Timeouts = field(default_factory=Timeouts)
    sources: Sources = field(default_factory=Sources)
    limits: Limits = field(default_factory=Limits)
    browser: Path = Path("~/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome").expanduser()
    ignored: tuple[str, ...] = ()     # keys in the file the tool does not read, sorted

    def student(self, name: str) -> Student:
        if name not in self.students:
            raise ConfigError(f"unknown learner {name!r}; known: {', '.join(self.students)}")
        return self.students[name]

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def log_path(self) -> Path:
        return self.root / "logs" / "school-notes.log"


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _known(table: dict, names, where: str, ignored: list[str]) -> dict:
    """The keys this tool reads; every other key goes to `ignored` as `<where>.<key>`."""
    ignored += sorted(f"{where}{k}" for k in table if k not in names)
    return {k: v for k, v in table.items() if k in names}


def _sub(cls, table: dict | None, where: str, ignored: list[str]):
    values = _known(dict(table or {}), {f.name for f in fields(cls)}, where, ignored)
    for key, value in values.items():
        if type(value) not in (int, float) or value < 0:
            raise ConfigError(f"[{where.rstrip('.')}] {key} must be a non-negative number")
    return cls(**values)


def _student(name: str, t: dict, ignored: list[str]) -> Student:
    if not re.fullmatch(r"[a-z0-9-]+", name):
        raise ConfigError(f"learner name {name!r} must be lowercase ascii")
    t = _known(t, {"site_repo", "drive_root", "grade", "local_repo"}, f"students.{name}.", ignored)
    try:
        grade = t["grade"]
        if type(grade) is not int or grade < 1:
            raise ConfigError(f"[students.{name}] grade must be a positive integer")
        return Student(name=name, site_repo=t["site_repo"], drive_root=t["drive_root"], grade=grade,
                       local_repo=_path(t["local_repo"]) if "local_repo" in t else None)
    except KeyError as exc:
        raise ConfigError(f"[students.{name}] missing {exc.args[0]}") from None


def parse(data: dict) -> Config:
    ignored: list[str] = []
    top = _known(data, {"root", "browser", "git", "students", "timeouts", "sources", "limits"}, "", ignored)
    git = _known(top.get("git", {}), {"name", "email"}, "git.", ignored)
    try:
        name, email = git["name"], git["email"]
    except KeyError as exc:
        raise ConfigError(f"[git] missing {exc.args[0]}") from None
    return Config(
        root=_path(top.get("root", "~/.local/share/school-notes")),
        git_name=name, git_email=email,
        students={n: _student(n, t, ignored) for n, t in top.get("students", {}).items()},
        timeouts=_sub(Timeouts, top.get("timeouts"), "timeouts.", ignored),
        sources=_sub(Sources, top.get("sources"), "sources.", ignored),
        limits=_sub(Limits, top.get("limits"), "limits.", ignored),
        **({"browser": _path(top["browser"])} if "browser" in top else {}),
        ignored=tuple(sorted(ignored)),
    )


def load(path: Path | None = None) -> Config:
    path = path or DEFAULT_PATH
    try:
        with open(path, "rb") as stream:
            cfg = parse(tomllib.load(stream))
    except FileNotFoundError:
        raise ConfigError(f"configuration missing: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    if cfg.ignored:
        print(f"sn: {path}: not used, ignored: {', '.join(cfg.ignored)}", file=sys.stderr)
    return cfg
