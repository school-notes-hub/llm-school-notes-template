"""E-mail notices (plan 8.4): msmtp, at most one per learner and error type per day.

A notice carries the learner, run id, step, error class, a short message and the next
step – never note content, photos or personal data. An msmtp failure is only logged."""

import subprocess
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from ..log import Log, today
from ..state.files import read_json, write_json


@dataclass(frozen=True)
class Notice:
    student: str
    kind: str        # daily filter key, e.g. "needs_owner:notes", "prerequisite:login"
    run_id: str
    step: str
    error_class: str
    message: str
    todo: str


@dataclass(frozen=True)
class Mailer:
    msmtprc: Path
    to: str
    state: Path          # state/notify.json
    log: Log
    timeout_s: float = 60
    msmtp: str = "msmtp"

    def send(self, notice: Notice) -> bool:
        """Send unless the same learner+kind was already mailed today. True: mail went out."""
        sent = read_json(self.state, {}) or {}
        key = f"{notice.student}:{notice.kind}"
        if sent.get(key) == today():
            self.log.event("notify.skip", target=key)
            return False
        if not self._deliver(render(notice, self.to)):
            return False
        sent = {k: v for k, v in sent.items() if v == today()}
        sent[key] = today()
        write_json(self.state, sent)
        self.log.event("notify.mail", target=key)
        return True

    def send_once(self, notice: Notice) -> bool | None:
        """Mail once ever: True means sent, False already sent, None delivery failed."""
        path = self.state.with_name("notify-once.json")
        done = set(read_json(path, []) or [])
        key = f"{notice.student}:{notice.kind}"
        if key in done:
            return False
        if self._deliver(render(notice, self.to)):
            write_json(path, sorted(done | {key}))
            self.log.event("notify.mail_once", target=key)
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
    message["Subject"] = f"School Notes – {notice.student}: {notice.error_class} ({notice.step})"
    message.set_content(
        f"Tanuló: {notice.student}\n"
        f"Futás: {notice.run_id or '-'}\n"
        f"Lépés: {notice.step}\n"
        f"Hibaosztály: {notice.error_class}\n"
        f"Üzenet: {notice.message[:500]}\n"
        f"Teendő: {notice.todo or '-'}\n\n"
        f"Részletek: school-notes status {notice.student}\n")
    return message
