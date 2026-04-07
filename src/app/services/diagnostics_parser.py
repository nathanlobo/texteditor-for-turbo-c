from __future__ import annotations

import re

from ..domain.models import Diagnostic, Severity


LINE_PATTERN = re.compile(r"(?P<file>[^\s:]+)[:(](?P<line>\d+)[):]?\s*(?P<msg>.+)")


def parse_diagnostics(output: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        lower = line.lower()
        severity = Severity.INFO
        if "error" in lower:
            severity = Severity.ERROR
        elif "warning" in lower:
            severity = Severity.WARNING

        match = LINE_PATTERN.search(line)
        if match:
            diagnostics.append(
                Diagnostic(
                    severity=severity,
                    file=match.group("file"),
                    line=int(match.group("line")),
                    message=match.group("msg"),
                )
            )
        else:
            diagnostics.append(Diagnostic(severity=severity, message=line))

    return diagnostics
