from __future__ import annotations

from pathlib import Path

from ..domain.models import ActionResult
from .diagnostics_parser import parse_diagnostics
from .dosbox_service import DosBoxService


class TurboCService:
    def __init__(self, dosbox_service: DosBoxService) -> None:
        self._dosbox = dosbox_service

    def compile(self, dosbox_exe: str, turboc_root: str, project_root: str, source_file: str) -> tuple[ActionResult, str]:
        normalized_source = source_file.replace("/", "\\")
        turbo_path = Path(turboc_root)
        project_path = Path(project_root)
        dos_turbo_root = f"C:\\{turbo_path.name}"
        dos_project_root = f"{dos_turbo_root}\\{project_path.name}"
        # Use an 8.3 filename so DOS redirection writes exactly the expected file.
        compile_log_name = "TCBUILD.LOG"
        compile_log_path = Path(project_root) / compile_log_name
        real_file_path = project_path / source_file
        
        commands = [
            "d:",
            # Set PATH to include BIN so tlink.exe can be found during linking.
            f"PATH {dos_turbo_root}\\BIN;%PATH%",
            # Compile with explicit include/lib paths to match IDE behavior.
            f"{dos_turbo_root}\\BIN\\TCC.EXE -I{dos_turbo_root}\\INCLUDE -L{dos_turbo_root}\\LIB {dos_project_root}\\{normalized_source} {dos_turbo_root}\\LIB\\GRAPHICS.LIB > {dos_project_root}\\{compile_log_name}",
        ]
        result = self._dosbox.run_dos_commands(dosbox_exe, turboc_root, project_root, commands)

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
        normalized_executable = executable_name.replace("/", "\\")
        run_commands = [
            "d:",
            normalized_executable,
        ]
        return self._dosbox.start_program_session(dosbox_exe, turboc_root, project_root, run_commands, fullscreen=True)
