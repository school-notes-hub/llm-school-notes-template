"""Error classes of plan 8.1. Each class has exactly one documented outcome."""


class SnError(Exception):
    """Base class; `kind` names the 8.1 class, `todo` is the owner's next step."""

    kind = "program"

    def __init__(self, message: str, *, todo: str = "", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.todo = todo
        self.details = details or {}


class Prerequisite(SnError):
    """Missing prerequisite before a run: nothing starts, daily e-mail, retried next hour."""

    kind = "prerequisite"


class Transient(SnError):
    """May pass by itself: retried inside the step, then in the next two runs."""

    kind = "transient"


class BadWork(SnError):
    """The LLM worked but its output is unusable: rerun on the same branch, two strikes."""

    kind = "bad_work"


class NeedsOwner(SnError):
    """Only the owner can decide: the run stops in its phase, e-mail at once."""

    kind = "needs_owner"


class Race(SnError):
    """Push rejected because someone pushed first; not an error, the caller rebuilds."""

    kind = "race"
