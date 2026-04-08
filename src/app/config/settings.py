from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


def resolve_dosbox_executable_path(dosbox_exe: str, turboc_root: str) -> Path | None:
    turbo_root_text = turboc_root.strip()
    if turbo_root_text:
        turbo_root = Path(turbo_root_text).expanduser()
        if turbo_root.exists() and turbo_root.is_dir():
            likely_candidates = [
                turbo_root / "DOSBox-0.74" / "DOSBox.exe",
                turbo_root / "DOSBox.exe",
            ]
            for candidate in likely_candidates:
                if candidate.exists() and candidate.is_file():
                    return candidate

            for candidate in turbo_root.rglob("DOSBox.exe"):
                if candidate.is_file():
                    return candidate

    explicit_path_text = dosbox_exe.strip()
    if explicit_path_text:
        explicit_path = Path(explicit_path_text).expanduser()
        if explicit_path.exists() and explicit_path.is_file():
            return explicit_path

    return None


@dataclass(slots=True)
class AppSettings:
    dosbox_exe: str = ""
    turboc_root: str = ""
    project_root: str = ""
    window_geometry: str = ""
    window_display_mode: str = "normal"
    show_output_in_fullscreen: bool = True
    zoom_level: int = 0
    theme_mode: str = "light"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def resolved_dosbox_executable(self) -> Path | None:
        return resolve_dosbox_executable_path(self.dosbox_exe, self.turboc_root)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AppSettings":
        try:
            zoom_level = int(data.get("zoom_level", 0))
        except (TypeError, ValueError):
            zoom_level = 0

        theme_mode = str(data.get("theme_mode", "light")).lower()
        if theme_mode not in {"light", "dark"}:
            theme_mode = "light"

        return cls(
            dosbox_exe=data.get("dosbox_exe", ""),
            turboc_root=data.get("turboc_root", ""),
            project_root=data.get("project_root", ""),
            window_geometry=data.get("window_geometry", ""),
            window_display_mode=data.get("window_display_mode", "normal"),
            show_output_in_fullscreen=data.get("show_output_in_fullscreen", True),
            zoom_level=zoom_level,
            theme_mode=theme_mode,
        )

    def validate(self) -> list[str]:
        errors: list[str] = []

        dosbox = Path(self.dosbox_exe)
        turbo = Path(self.turboc_root)
        project = Path(self.project_root)
        resolved_dosbox = self.resolved_dosbox_executable()

        if not self.turboc_root:
            errors.append("Turbo C root path is required.")
        elif not turbo.exists() or not turbo.is_dir():
            errors.append("Turbo C root directory is invalid.")
        elif resolved_dosbox is None:
            errors.append("Unable to auto-detect DOSBox.exe from the Turbo C root.")

        if not self.turboc_root and self.dosbox_exe and not dosbox.exists():
            errors.append("DOSBox executable path does not exist.")

        if not self.project_root:
            errors.append("Project root path is required.")
        elif not project.exists() or not project.is_dir():
            errors.append("Project root directory is invalid.")

        return errors
