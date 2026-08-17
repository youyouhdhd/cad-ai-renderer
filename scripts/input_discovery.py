#!/usr/bin/env python3
"""Classify attached/local paths into one 3D model and zero or more images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

MODEL_PRIORITY = {
    ".step": 100,
    ".stp": 100,
    ".glb": 90,
    ".gltf": 85,
    ".obj": 80,
    ".stl": 75,
    ".ply": 70,
    ".3mf": 65,
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
SKIP_DIR_NAMES = {".git", ".venv", "venv", "node_modules", "output", "outputs", "dist", "build"}


class InputDiscoveryError(ValueError):
    """Raised when attachment classification cannot choose a model safely."""


def _expand_inputs(paths: Iterable[str | Path]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_file():
            files.append(path)
            continue
        for candidate in sorted(path.rglob("*")):
            if any(part in SKIP_DIR_NAMES or part.startswith(".") for part in candidate.relative_to(path).parts[:-1]):
                continue
            if candidate.is_file():
                files.append(candidate.resolve())
    dedup: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        if path not in seen:
            seen.add(path)
            dedup.append(path)
    return dedup


def discover_inputs(
    inputs: Sequence[str | Path] | None = None,
    explicit_model: str | Path | None = None,
    explicit_references: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    files = _expand_inputs(inputs or [])
    if explicit_model:
        model_path = Path(explicit_model).expanduser().resolve()
        if not model_path.exists():
            raise FileNotFoundError(model_path)
        if model_path not in files:
            files.insert(0, model_path)
    else:
        model_path = None

    references = [Path(path).expanduser().resolve() for path in (explicit_references or [])]
    for path in references:
        if not path.exists():
            raise FileNotFoundError(path)
        if path not in files:
            files.append(path)

    model_candidates = [path for path in files if path.suffix.lower() in MODEL_PRIORITY]
    image_candidates = [path for path in files if path.suffix.lower() in IMAGE_EXTENSIONS]

    if model_path is None:
        if not model_candidates:
            raise InputDiscoveryError(
                "No supported 3D model was found. Attach STEP/STP, GLB, GLTF, OBJ, STL, PLY, or 3MF."
            )
        ranked = sorted(model_candidates, key=lambda path: (-MODEL_PRIORITY[path.suffix.lower()], path.name.lower()))
        top_priority = MODEL_PRIORITY[ranked[0].suffix.lower()]
        top = [path for path in ranked if MODEL_PRIORITY[path.suffix.lower()] == top_priority]
        if len(top) > 1:
            choices = ", ".join(path.name for path in top)
            raise InputDiscoveryError(
                f"Multiple equally preferred model files were found ({choices}). Pass --model for the intended one."
            )
        model_path = ranked[0]
    elif model_path.suffix.lower() not in MODEL_PRIORITY:
        raise InputDiscoveryError(f"Unsupported 3D model extension: {model_path.suffix}")

    reference_paths: list[Path] = []
    seen_refs: set[Path] = set()
    for path in [*references, *image_candidates]:
        if path == model_path or path in seen_refs:
            continue
        seen_refs.add(path)
        reference_paths.append(path)

    used = {model_path, *reference_paths}
    ignored = [path for path in files if path not in used]
    return {
        "model": str(model_path),
        "references": [
            {
                "path": str(path),
                "roles": ["mixed"],
                "notes": "Role to be inferred from the attached image and the user's request.",
                "source": "attachment",
            }
            for path in reference_paths
        ],
        "ignored": [str(path) for path in ignored],
        "model_candidates": [str(path) for path in model_candidates],
        "image_candidates": [str(path) for path in image_candidates],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--model")
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("--output")
    args = parser.parse_args()
    result = discover_inputs(args.input, args.model, args.reference)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
