from __future__ import annotations

import sys
from pathlib import Path


def asset_path(*parts: str) -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidate = Path(frozen_root) / "src" / "app" / "assets" / Path(*parts)
        if candidate.exists():
            return candidate

    source_candidate = Path(__file__).resolve().parent / "assets" / Path(*parts)
    if source_candidate.exists():
        return source_candidate

    fallback_candidate = Path(__file__).resolve().parents[2] / "src" / "app" / "assets" / Path(*parts)
    if fallback_candidate.exists():
        return fallback_candidate

    return source_candidate