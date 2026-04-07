from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class Diagnostic:
    severity: Severity
    message: str
    file: str | None = None
    line: int | None = None


class SessionState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass(slots=True)
class ActionResult:
    ok: bool
    output: str
    return_code: int | None = None
