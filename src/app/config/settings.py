from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class AppSettings:
    dosbox_exe: str = ""
    turboc_root: str = ""
    project_root: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "AppSettings":
        return cls(
            dosbox_exe=data.get("dosbox_exe", ""),
            turboc_root=data.get("turboc_root", ""),
            project_root=data.get("project_root", ""),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []

        dosbox = Path(self.dosbox_exe)
        turbo = Path(self.turboc_root)
        project = Path(self.project_root)

        if not self.dosbox_exe:
            errors.append("DOSBox executable path is required.")
        elif not dosbox.exists():
            errors.append("DOSBox executable path does not exist.")

        if not self.turboc_root:
            errors.append("Turbo C root path is required.")
        elif not turbo.exists() or not turbo.is_dir():
            errors.append("Turbo C root directory is invalid.")

        if not self.project_root:
            errors.append("Project root path is required.")
        elif not project.exists() or not project.is_dir():
            errors.append("Project root directory is invalid.")

        return errors
