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
            self._process = None
            self.state = SessionState.STOPPED
            return ActionResult(ok=True, output="No active DOSBox session.")

        pid = self._process.pid
        if pid is not None:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, check=False)

        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                self._process.kill()
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

        self._process = None
        self.state = SessionState.STOPPED
        return ActionResult(ok=True, output="DOSBox session stopped.")

    def _create_shortcut_safe_conf(
        self,
        dosbox_exe: str,
        turboc_root: str,
        project_root: str,
        *,
        fullscreen: bool = False,
    ) -> Path | None:
        dosbox_path = Path(dosbox_exe)
        turbo_path = Path(turboc_root)
        project_path = Path(project_root)

        mapper_candidates = [
            turbo_path / "mapper-2.0.map",
            dosbox_path.parent / "mapper-0.74.map",
            dosbox_path.parent / "mapper.map",
        ]

        mapper_source: Path | None = None
        for candidate in mapper_candidates:
            if candidate.exists() and candidate.is_file():
                mapper_source = candidate
                break

        if mapper_source is None:
            return None

        safe_mapper_path = project_path / "TCSAFE.MAP"
        safe_conf_path = project_path / "TCSAFE.CONF"

        try:
            content = mapper_source.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

        safe_lines: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("key_"):
                event_name = stripped.split()[0]
                # Keep DOSBox function keys available, suppress most key events to
                # reduce accidental host-shortcut leakage into DOS programs.
                if event_name.startswith("key_f"):
                    safe_lines.append(line)
                else:
                    safe_lines.append(event_name)
            else:
                safe_lines.append(line)

        try:
            safe_mapper_path.write_text("\n".join(safe_lines) + "\n", encoding="utf-8")
            safe_conf_path.write_text(
                "[sdl]\n"
                "usescancodes=false\n"
                f"fullscreen={'true' if fullscreen else 'false'}\n"
                f"mapperfile={safe_mapper_path}\n",
                encoding="utf-8",
            )
        except OSError:
            return None

        return safe_conf_path

    def start_program_session(
        self,
        dosbox_exe: str,
        turboc_root: str,
        project_root: str,
        run_commands: list[str],
        *,
        fullscreen: bool = False,
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
        safe_conf_path = self._create_shortcut_safe_conf(dosbox_exe, turboc_root, project_root, fullscreen=fullscreen)
        commands = [
            str(dosbox_path),
        ]

        if safe_conf_path is not None:
            commands.extend(["-conf", str(safe_conf_path)])

        if fullscreen:
            commands.append("-fullscreen")

        commands.extend([
            "-noconsole",
            "-c",
            f"mount c \"{turbo_path.parent}\"",
            "-c",
            f"mount d \"{proj_path}\"",
            "-c",
            "c:",
            "-c",
            f"PATH C:\\{turbo_path.name}\\BIN;%PATH%",
        ])

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
            if safe_conf_path is not None:
                return ActionResult(
                    ok=True,
                    output=(
                        f"Program started in DOSBox {'fullscreen ' if fullscreen else ''}(shortcut-safe mode). "
                        "Close DOSBox or click Stop Session when done."
                    ),
                )
            return ActionResult(
                ok=True,
                output=(
                    f"Program started in DOSBox {'fullscreen ' if fullscreen else ''}. "
                    "Close DOSBox or click Stop Session when done."
                ),
            )
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
