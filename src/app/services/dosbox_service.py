from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from tempfile import gettempdir

from ..config.settings import resolve_dosbox_executable_path
from ..domain.models import ActionResult, SessionState


class DosBoxService:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self.state = SessionState.STOPPED

    def _compatibility_root(self, turboc_root: str, project_root: str) -> Path:
        turbo_path = Path(turboc_root).resolve()
        project_path = Path(project_root).resolve()
        cache_key = hashlib.sha1(f"{turbo_path}|{project_path}".encode("utf-8")).hexdigest()[:16]
        root = Path(gettempdir()) / "turbo-c-upgrade" / "dosbox" / cache_key
        root.mkdir(parents=True, exist_ok=True)

        alias_targets = {
            "TC": turbo_path,
            "TURBOC3": turbo_path,
            "PROJECT": project_path,
        }

        for alias_name, target_path in alias_targets.items():
            alias_path = root / alias_name
            if alias_path.exists():
                continue
            if not self._create_directory_link(alias_path, target_path):
                raise OSError(f"Unable to create DOSBox alias {alias_name} -> {target_path}")

        return root

    def _create_directory_link(self, link_path: Path, target_path: Path) -> bool:
        try:
            link_path.symlink_to(target_path, target_is_directory=True)
            return True
        except OSError:
            pass

        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.returncode == 0

    def _resolve_dosbox_path(self, dosbox_exe: str, turboc_root: str) -> Path | None:
        return resolve_dosbox_executable_path(dosbox_exe, turboc_root)

    def start_turboc_session(self, dosbox_exe: str, turboc_root: str, project_root: str) -> ActionResult:
        if self._process and self._process.poll() is None:
            self.state = SessionState.RUNNING
            return ActionResult(ok=True, output="DOSBox session already running.")

        dosbox_path = self._resolve_dosbox_path(dosbox_exe, turboc_root)
        turbo_path = Path(turboc_root)
        proj_path = Path(project_root)

        if dosbox_path is None:
            self.state = SessionState.ERROR
            return ActionResult(ok=False, output="Unable to locate DOSBox.exe from the Turbo C root.")

        self.state = SessionState.STARTING
        compatibility_root = self._compatibility_root(turboc_root, project_root)
        commands = [
            str(dosbox_path),
            "-noconsole",
            "-c",
            f"mount c \"{compatibility_root}\"",
            "-c",
            f"mount d \"{proj_path}\"",
            "-c",
            "c:",
            "-c",
            "cd \\TC\\BIN",
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
        blocked_events = {"key_altenter", "key_ctrlesc", "key_ctrlesc"}
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("key_"):
                event_name = stripped.split()[0]
                if event_name in blocked_events:
                    continue
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
                f"windowresolution={'1024x768' if not fullscreen else 'desktop'}\n"
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
        close_on_any_key: bool = False,
    ) -> ActionResult:
        dosbox_path = self._resolve_dosbox_path(dosbox_exe, turboc_root)
        turbo_path = Path(turboc_root)
        proj_path = Path(project_root)

        if dosbox_path is None:
            self.state = SessionState.ERROR
            return ActionResult(ok=False, output="Unable to locate DOSBox.exe from the Turbo C root.")

        if self._process and self._process.poll() is None:
            self._process.terminate()

        self.state = SessionState.STARTING
        compatibility_root = self._compatibility_root(turboc_root, project_root)
        safe_conf_path = self._create_shortcut_safe_conf(str(dosbox_path), turboc_root, project_root, fullscreen=fullscreen)
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
            f"mount c \"{compatibility_root}\"",
            "-c",
            f"mount d \"{proj_path}\"",
            "-c",
            "c:",
            "-c",
            "PATH C:\\TC\\BIN;%PATH%",
        ])

        for command in run_commands:
            commands.extend(["-c", command])

        if close_on_any_key:
            commands.extend(["-c", "pause", "-c", "exit"])

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
                        f"Program started in DOSBox {'fullscreen ' if fullscreen else 'windowed '}(shortcut-safe mode). "
                        "Press any key to close it."
                    ),
                )
            return ActionResult(
                ok=True,
                output=(
                        f"Program started in DOSBox {'fullscreen ' if fullscreen else 'windowed '}. "
                    "Press any key to close it."
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
        dosbox_path = self._resolve_dosbox_path(dosbox_exe, turboc_root)
        if dosbox_path is None:
            return ActionResult(ok=False, output="Unable to locate DOSBox.exe from the Turbo C root.")

        args: list[str] = [str(dosbox_path), "-noconsole"]
        compatibility_root = self._compatibility_root(turboc_root, project_root)
        args.extend(["-c", f"mount c \"{compatibility_root}\""])
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
