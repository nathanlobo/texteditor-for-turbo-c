from __future__ import annotations

import subprocess
from pathlib import Path

from ..domain.models import ActionResult, SessionState


class DosBoxService:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self.state = SessionState.STOPPED

    def start_turboc_session(self, dosbox_exe: str, turboc_root: str, project_root: str) -> ActionResult:
        if self._process and self._process.poll() is None:
            self.state = SessionState.RUNNING
            return ActionResult(ok=True, output="DOSBox session already running.")

        dosbox_path = Path(dosbox_exe)
        turbo_path = Path(turboc_root)
        proj_path = Path(project_root)

        if not dosbox_path.exists():
            self.state = SessionState.ERROR
            return ActionResult(ok=False, output="DOSBox executable not found.")

        self.state = SessionState.STARTING
        turbo_path = Path(turboc_root)
        commands = [
            str(dosbox_path),
            "-noconsole",
            "-c",
            f"mount c \"{turbo_path.parent}\"",
            "-c",
            f"mount d \"{proj_path}\"",
            "-c",
            "c:",
            "-c",
            f"cd \\{turbo_path.name}\\BIN",
            "-c",
            "TC.EXE",
        ]

        try:
            self._process = subprocess.Popen(
                commands,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.state = SessionState.RUNNING
            return ActionResult(ok=True, output="Turbo C session started in DOSBox.")
        except OSError as exc:
            self.state = SessionState.ERROR
            return ActionResult(ok=False, output=f"Failed to start DOSBox: {exc}")

    def stop_session(self) -> ActionResult:
        if not self._process or self._process.poll() is not None:
            self.state = SessionState.STOPPED
            return ActionResult(ok=True, output="No active DOSBox session.")

        self._process.terminate()
        self.state = SessionState.STOPPED
        return ActionResult(ok=True, output="DOSBox session stopped.")

    def start_program_session(
        self,
        dosbox_exe: str,
        turboc_root: str,
        project_root: str,
        run_commands: list[str],
    ) -> ActionResult:
        dosbox_path = Path(dosbox_exe)
        turbo_path = Path(turboc_root)
        proj_path = Path(project_root)

        if not dosbox_path.exists():
            self.state = SessionState.ERROR
            return ActionResult(ok=False, output="DOSBox executable not found.")

        if self._process and self._process.poll() is None:
            self._process.terminate()

        self.state = SessionState.STARTING
        commands = [
            str(dosbox_path),
            "-noconsole",
            "-c",
            f"mount c \"{turbo_path.parent}\"",
            "-c",
            f"mount d \"{proj_path}\"",
            "-c",
            "c:",
            "-c",
            f"PATH C:\\{turbo_path.name}\\BIN;%PATH%",
        ]

        for command in run_commands:
            commands.extend(["-c", command])

        try:
            self._process = subprocess.Popen(
                commands,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.state = SessionState.RUNNING
            return ActionResult(ok=True, output="Program started in DOSBox. Close DOSBox or click Stop Session when done.")
        except OSError as exc:
            self.state = SessionState.ERROR
            return ActionResult(ok=False, output=f"Failed to start DOSBox: {exc}")

    def run_dos_commands(
        self,
        dosbox_exe: str,
        turboc_root: str,
        project_root: str,
        commands: list[str],
    ) -> ActionResult:
        dosbox_path = Path(dosbox_exe)
        if not dosbox_path.exists():
            return ActionResult(ok=False, output="DOSBox executable not found.")

        args: list[str] = [str(dosbox_path), "-noconsole"]
        turbo_path = Path(turboc_root)
        args.extend(["-c", f"mount c \"{turbo_path.parent}\""])
        args.extend(["-c", f"mount d \"{Path(project_root)}\""])
        args.extend(["-c", "c:"])

        for command in commands:
            args.extend(["-c", command])

        args.extend(["-c", "exit"])

        try:
            completed = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=60,
                check=False,
            )
            ok = completed.returncode == 0
            return ActionResult(ok=ok, output=completed.stdout or "", return_code=completed.returncode)
        except subprocess.TimeoutExpired:
            return ActionResult(ok=False, output="DOSBox command timed out.")
        except OSError as exc:
            return ActionResult(ok=False, output=f"Failed to execute DOSBox command: {exc}")
