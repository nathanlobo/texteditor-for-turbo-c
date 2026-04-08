from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from ..domain.models import ActionResult
from .diagnostics_parser import parse_diagnostics
from .dosbox_service import DosBoxService


class TurboCService:
    def __init__(self, dosbox_service: DosBoxService) -> None:
        self._dosbox = dosbox_service

    def _build_key(self, project_root: str) -> str:
        resolved_project = Path(project_root).resolve()
        return hashlib.sha1(str(resolved_project).encode("utf-8")).hexdigest()[:8].upper()

    def _build_root(self, turboc_root: str, project_root: str) -> Path:
        turbo_path = Path(turboc_root).resolve()
        return turbo_path / "_build" / self._build_key(project_root)

    def _sync_project_to_build_root(self, project_root: Path, build_root: Path) -> None:
        if build_root.exists():
            shutil.rmtree(build_root)

        build_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            project_root,
            build_root,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "__pycache__",
                ".mypy_cache",
                ".pytest_cache",
                "build",
                "dist",
                "*.pyc",
                "*.pyo",
                "*.obj",
                "*.exe",
                "*.map",
                "*.log",
                "*.conf",
                "TCBUILD.LOG",
                "TCSAFE.*",
            ),
        )

    def _relocate_generated_artifacts(self, project_root: Path, build_root: Path) -> None:
        ignored_dirs = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache", "build", "dist", "_build"}
        generated_suffixes = {".exe", ".obj", ".map", ".conf", ".tds", ".bak"}

        for file_path in project_root.rglob("*"):
            if not file_path.is_file():
                continue

            relative_path = file_path.relative_to(project_root)
            if any(part in ignored_dirs for part in relative_path.parts):
                continue

            file_name = file_path.name.lower()
            if file_name == "tcbuild.log" or file_name.startswith("tcsafe.") or file_path.suffix.lower() in generated_suffixes:
                destination = build_root / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    destination.unlink()
                shutil.move(str(file_path), str(destination))

    def compile(self, dosbox_exe: str, turboc_root: str, project_root: str, source_file: str) -> tuple[ActionResult, str]:
        normalized_source = source_file.replace("/", "\\")
        project_path = Path(project_root).resolve()
        build_root = self._build_root(turboc_root, project_root)
        self._sync_project_to_build_root(project_path, build_root)
        self._relocate_generated_artifacts(project_path, build_root)

        turbo_path = Path(turboc_root).resolve()
        dos_turbo_root = f"C:\\{turbo_path.name}"
        dos_build_root = f"{dos_turbo_root}\\_build\\{build_root.name}"
        # Use an 8.3 filename so DOS redirection writes exactly the expected file.
        compile_log_name = "TCBUILD.LOG"
        compile_log_path = build_root / compile_log_name
        real_file_path = project_path / source_file
        
        commands = [
            "d:",
            # Set PATH to include BIN so tlink.exe can be found during linking.
            f"PATH {dos_turbo_root}\\BIN;%PATH%",
            # Compile with explicit include/lib paths to match IDE behavior.
            f"{dos_turbo_root}\\BIN\\TCC.EXE -I{dos_turbo_root}\\INCLUDE -L{dos_turbo_root}\\LIB {dos_build_root}\\{normalized_source} {dos_turbo_root}\\LIB\\GRAPHICS.LIB > d:\\{compile_log_name}",
        ]
        result = self._dosbox.run_dos_commands(dosbox_exe, turboc_root, str(build_root), commands)

        output_parts: list[str] = []
        if result.output.strip():
            output_parts.append(result.output.strip())

        if compile_log_path.exists():
            try:
                file_output = compile_log_path.read_text(encoding="cp1252", errors="replace").strip()
                if file_output:
                    output_parts.append(file_output)
            except OSError:
                pass

        output_text = "\n".join(part for part in output_parts if part).strip() or result.output

        diagnostics = parse_diagnostics(output_text)
        rendered_lines = [
            f"[FILE] {real_file_path}",
            "[DIAGNOSTICS]",
        ]
        rendered_lines.extend(
            f"[{d.severity.value.upper()}] "
            f"{f'{d.file}:{d.line} ' if d.file and d.line else ''}{d.message}"
            for d in diagnostics
        )
        rendered_lines.append("[RAW OUTPUT]")
        rendered_lines.append(output_text or "(no output)")
        rendered = "\n".join(rendered_lines)

        result_with_output = ActionResult(ok=result.ok, output=output_text, return_code=result.return_code)
        return result_with_output, rendered

    def run_program(self, dosbox_exe: str, turboc_root: str, project_root: str, executable_name: str) -> ActionResult:
        build_root = self._build_root(turboc_root, project_root)
        if not build_root.exists():
            project_path = Path(project_root).resolve()
            self._sync_project_to_build_root(project_path, build_root)
            self._relocate_generated_artifacts(project_path, build_root)

        executable_path = Path(executable_name).with_suffix(".EXE")
        relative_folder = executable_path.parent.as_posix().replace("/", "\\")
        run_commands = ["d:"]
        if relative_folder not in {"", "."}:
            run_commands.append(f'cd "{relative_folder}"')
        run_commands.append(executable_path.name)
        return self._dosbox.start_program_session(
            dosbox_exe,
            turboc_root,
            str(build_root),
            run_commands,
            fullscreen=False,
            close_on_any_key=True,
        )
