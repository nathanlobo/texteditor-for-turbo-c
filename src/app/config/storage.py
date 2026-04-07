from __future__ import annotations

import json
from pathlib import Path

from .settings import AppSettings


class SettingsStorage:
    def __init__(self, file_path: Path | None = None) -> None:
        default_path = Path.home() / ".turbo_c_upgrade" / "settings.json"
        self.file_path = file_path or default_path

    def load(self) -> AppSettings:
        if not self.file_path.exists():
            return AppSettings()

        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return AppSettings()
            return AppSettings.from_dict(data)
        except (json.JSONDecodeError, OSError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(settings.to_dict(), indent=2)
        self.file_path.write_text(payload, encoding="utf-8")
