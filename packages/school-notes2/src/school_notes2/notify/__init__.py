"""Content-free completion and incident mail; item notices stay in status."""

import subprocess
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from ..log import Log, now_iso
from ..mcp.redact import redact
from ..state.files import read_json, write_json


@dataclass(frozen=True)
class Notice:
    student: str
    kind: str        # stable receipt key; mailed() defines the allowed notices
    run_id: str
    step: str
    error_class: str
    message: str
    todo: str


def mailed(notice: Notice) -> bool:
    if notice.kind.startswith("error:"):
        return True
    return notice.kind.startswith(("completion:", "nightly:")) and notice.kind.split(":")[2:3] in (["done"], ["closed"], ["retry_nightly"])


@dataclass(frozen=True)
class Mailer:
    msmtprc: Path
    to: str
    state: Path          # state/notify.json
    log: Log
    timeout_s: float = 60
    msmtp: str = "msmtp"

    def send(self, notice: Notice) -> bool:
        """Use the same durable receipt as send_once, regardless of entry point."""
        return self.send_once(notice) is True

    def send_once(self, notice: Notice) -> bool | None:
        """Mail once ever: True means sent, False already sent, None delivery failed."""
        key = f"{notice.student}:{notice.kind}"
        if not mailed(notice):
            self.log.bind(student=notice.student).event("notify.suppressed", target=key)
            return False
        path = self.state.with_name("notify-once.json")
        done = set(read_json(path, []) or [])
        if key in done:
            return False
        if self._deliver(render(notice, self.to)):
            write_json(path, sorted(done | {key}))
            self.log.bind(student=notice.student).event("notify.mail_once", target=key)
            return True
        return None

    def _deliver(self, message: EmailMessage) -> bool:
        try:
            proc = subprocess.run([self.msmtp, f"--file={self.msmtprc}", "-t"],
                                  input=message.as_bytes(), capture_output=True,
                                  timeout=self.timeout_s)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.log.event("notify.mail", "error", level="error", message=type(exc).__name__)
            return False
        if proc.returncode != 0:
            self.log.event("notify.mail", "error", level="error", rc=proc.returncode,
                           message=proc.stderr.decode("utf-8", "replace")[:200])
            return False
        return True


def render(notice: Notice, to: str) -> EmailMessage:
    message = EmailMessage()
    message["To"] = to
    if mailed(notice):
        message["Subject"] = f"School Notes – {notice.error_class}"
        message.set_content(f"{redact(notice.message)}\n")
        return message
    message["Subject"] = f"School Notes – {notice.student}: {notice.error_class} ({notice.step})"
    message.set_content(
        f"Tanuló: {notice.student}\n"
        f"Futás: {notice.run_id or '-'}\n"
        f"Lépés: {notice.step}\n"
        f"Hibaosztály: {notice.error_class}\n"
        f"Időpont: {now_iso()}\n"
        f"Üzenet: {redact(notice.message)}\n"
        f"Teendő: {notice.todo or '-'}\n\n"
        f"Részletek: school-notes status {notice.student}\n")
    return message
