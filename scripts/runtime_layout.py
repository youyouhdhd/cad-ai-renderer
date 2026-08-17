#!/usr/bin/env python3
"""Cross-platform output layout helpers.

Windows reserves device names such as ``AUX`` regardless of letter case or
extension. The pipeline therefore writes deterministic CAD passes to the
portable ``auxiliary`` directory. Existing runs that used ``aux`` on POSIX
remain readable through the legacy fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

AUXILIARY_DIRNAME = "auxiliary"
LEGACY_AUXILIARY_DIRNAME = "aux"


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def canonical_auxiliary_dir(run_dir: str | Path) -> Path:
    return Path(run_dir).expanduser().resolve() / AUXILIARY_DIRNAME


def legacy_auxiliary_dir(run_dir: str | Path) -> Path:
    return Path(run_dir).expanduser().resolve() / LEGACY_AUXILIARY_DIRNAME


def resolve_auxiliary_dir(
    run_dir: str | Path,
    *,
    create: bool = False,
    allow_legacy: bool = True,
) -> Path:
    """Return the canonical directory, or an existing legacy POSIX directory.

    New output is always created under ``auxiliary``. The legacy ``aux`` name
    is consulted only when reading an existing run and never created.
    """

    canonical = canonical_auxiliary_dir(run_dir)
    if _exists(canonical):
        return canonical
    if allow_legacy:
        legacy = legacy_auxiliary_dir(run_dir)
        if _exists(legacy):
            return legacy
    if create:
        canonical.mkdir(parents=True, exist_ok=True)
    return canonical


def output_layout(run_dir: str | Path, *, create: bool = False) -> dict[str, Path]:
    root = Path(run_dir).expanduser().resolve()
    layout = {
        "root": root,
        "auxiliary": root / AUXILIARY_DIRNAME,
        "planning": root / "planning",
        "candidates": root / "candidates",
        "final": root / "final",
    }
    if create:
        for key in ("root", "auxiliary", "planning", "candidates", "final"):
            layout[key].mkdir(parents=True, exist_ok=True)
    return layout


def manifest_paths(layout: dict[str, Path]) -> dict[str, Any]:
    return {key: str(value) for key, value in layout.items()}
