#!/usr/bin/env python3
"""Convert STEP/STP or common mesh files to GLB and write a model manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bbox_dict(bb: Any) -> dict[str, Any]:
    return {
        "min": [float(bb.xmin), float(bb.ymin), float(bb.zmin)],
        "max": [float(bb.xmax), float(bb.ymax), float(bb.zmax)],
        "size": [float(bb.xlen), float(bb.ylen), float(bb.zlen)],
        "diagonal": float((bb.xlen ** 2 + bb.ylen ** 2 + bb.zlen ** 2) ** 0.5),
    }


def _safe_volume(obj: Any) -> float | None:
    try:
        value = float(obj.Volume())
        return value if value >= 0 else None
    except Exception:
        return None


def _color_tuple(color: Any) -> list[float] | None:
    if color is None:
        return None
    try:
        return [float(value) for value in color.toTuple()]
    except Exception:
        return None


def _shape_type(obj: Any) -> str:
    try:
        return str(obj.ShapeType())
    except Exception:
        return type(obj).__name__


def _is_effectively_colorless(colors: Iterable[list[float] | None]) -> bool:
    present = [color[:3] for color in colors if color is not None]
    if not present:
        return True
    rounded = {tuple(round(channel, 3) for channel in color) for color in present}
    if len(rounded) == 1:
        only = next(iter(rounded))
        spread = max(only) - min(only)
        return spread < 0.08
    return False


def _import_step_cadquery(source: Path) -> tuple[Any, str]:
    try:
        import cadquery as cq
    except ImportError as exc:
        raise RuntimeError(
            "CadQuery is not installed. Install cadquery, or select geometry.converter=freecad."
        ) from exc

    try:
        assembly = cq.Assembly.importStep(str(source), unit="MM")
        mode = "assembly"
    except Exception:
        workplane = cq.importers.importStep(str(source))
        if not workplane.objects:
            raise RuntimeError(f"No shapes were imported from STEP file: {source}")
        assembly = cq.Assembly(name=source.stem)
        for index, obj in enumerate(workplane.objects, start=1):
            assembly.add(obj, name=f"part_{index:03d}")
        mode = "shape"
    return assembly, mode


def convert_with_cadquery(
    source: Path,
    output_glb: Path,
    linear_tolerance: float,
    angular_tolerance: float,
) -> dict[str, Any]:
    assembly, import_mode = _import_step_cadquery(source)
    output_glb.parent.mkdir(parents=True, exist_ok=True)
    assembly.save(
        str(output_glb),
        exportType="GLTF",
        tolerance=float(linear_tolerance),
        angularTolerance=float(angular_tolerance),
    )

    parts: list[dict[str, Any]] = []
    for key, node in assembly.objects.items():
        obj = getattr(node, "obj", None)
        if obj is None:
            continue
        try:
            located = obj.located(node.loc)
        except Exception:
            located = obj
        try:
            bbox = _bbox_dict(located.BoundingBox())
        except Exception:
            bbox = None
        location = None
        try:
            translation, rotation = node.loc.toTuple()
            location = {
                "translation": [float(v) for v in translation],
                "rotation_deg": [float(v) for v in rotation],
            }
        except Exception:
            pass
        parts.append(
            {
                "id": str(key),
                "name": str(getattr(node, "name", key)),
                "shape_type": _shape_type(obj),
                "color_rgba": _color_tuple(getattr(node, "color", None)),
                "volume_mm3": _safe_volume(obj),
                "bbox_mm": bbox,
                "location": location,
            }
        )

    compound = assembly.toCompound()
    global_bbox = _bbox_dict(compound.BoundingBox())
    colors = [part["color_rgba"] for part in parts]
    return {
        "converter": "cadquery",
        "cadquery_import_mode": import_mode,
        "units": "mm",
        "part_count": len(parts),
        "parts": parts,
        "bbox_mm": global_bbox,
        "source_has_useful_colors": not _is_effectively_colorless(colors),
    }


def _freecad_executable() -> str | None:
    return shutil.which("FreeCADCmd") or shutil.which("freecadcmd")


def convert_with_freecad(source: Path, output_glb: Path, script_dir: Path) -> dict[str, Any]:
    executable = _freecad_executable()
    if not executable:
        raise RuntimeError("FreeCADCmd/freecadcmd was not found in PATH")
    temporary_stl = output_glb.with_suffix(".freecad.stl")
    helper = script_dir / "freecad_step_export.py"
    command = [executable, str(helper), "--", str(source), str(temporary_stl)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not temporary_stl.exists():
        raise RuntimeError(
            "FreeCAD conversion failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    try:
        import trimesh
    except ImportError as exc:
        raise RuntimeError("trimesh is required for the FreeCAD fallback") from exc
    mesh = trimesh.load(str(temporary_stl), force="scene")
    output_glb.parent.mkdir(parents=True, exist_ok=True)
    output_glb.write_bytes(mesh.export(file_type="glb"))
    bounds = mesh.bounds.tolist() if getattr(mesh, "bounds", None) is not None else None
    temporary_stl.unlink(missing_ok=True)
    return {
        "converter": "freecad-stl-fallback",
        "units": "mm",
        "part_count": len(getattr(mesh, "geometry", {})) or 1,
        "parts": [],
        "bbox_mm": {"min": bounds[0], "max": bounds[1]} if bounds else None,
        "source_has_useful_colors": False,
        "warning": "FreeCAD fallback tessellates through STL and cannot preserve STEP colors or assembly IDs.",
    }


def convert_mesh(source: Path, output_glb: Path) -> dict[str, Any]:
    suffix = source.suffix.lower()
    if suffix == ".glb":
        output_glb.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != output_glb.resolve():
            shutil.copy2(source, output_glb)
    else:
        try:
            import trimesh
        except ImportError as exc:
            raise RuntimeError("trimesh is required to convert mesh files to GLB") from exc
        scene = trimesh.load(str(source), force="scene")
        output_glb.parent.mkdir(parents=True, exist_ok=True)
        output_glb.write_bytes(scene.export(file_type="glb"))
    try:
        import trimesh

        scene = trimesh.load(str(output_glb), force="scene")
        bounds = scene.bounds.tolist() if scene.bounds is not None else None
        part_count = len(scene.geometry)
    except Exception:
        bounds = None
        part_count = 0
    return {
        "converter": "passthrough" if suffix == ".glb" else "trimesh",
        "units": "source_units",
        "part_count": part_count,
        "parts": [],
        "bbox_mm": {"min": bounds[0], "max": bounds[1]} if bounds else None,
        "source_has_useful_colors": True,
    }


def convert_model(
    source: str | Path,
    output_glb: str | Path,
    manifest_path: str | Path,
    converter: str = "auto",
    linear_tolerance: float = 0.2,
    angular_tolerance: float = 0.1,
) -> dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    output_path = Path(output_glb).expanduser().resolve()
    manifest_file = Path(manifest_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    suffix = source_path.suffix.lower()
    script_dir = Path(__file__).resolve().parent
    errors: list[str] = []
    if suffix in {".step", ".stp"}:
        if converter in {"auto", "cadquery"}:
            try:
                details = convert_with_cadquery(
                    source_path, output_path, linear_tolerance, angular_tolerance
                )
            except Exception as exc:
                errors.append(f"CadQuery: {exc}")
                if converter == "cadquery":
                    raise
                details = None
        else:
            details = None
        if details is None and converter in {"auto", "freecad"}:
            try:
                details = convert_with_freecad(source_path, output_path, script_dir)
            except Exception as exc:
                errors.append(f"FreeCAD: {exc}")
                raise RuntimeError("All STEP conversion paths failed: " + " | ".join(errors)) from exc
        if details is None:
            raise RuntimeError(f"Unsupported converter for STEP: {converter}")
    else:
        if converter not in {"auto", "passthrough"}:
            errors.append(f"Requested converter {converter!r} is not used for mesh input")
        details = convert_mesh(source_path, output_path)

    manifest = {
        "source_path": str(source_path),
        "source_name": source_path.name,
        "source_extension": suffix,
        "source_sha256": _sha256(source_path),
        "glb_path": str(output_path),
        "glb_sha256": _sha256(output_path),
        "linear_tolerance": float(linear_tolerance),
        "angular_tolerance": float(angular_tolerance),
        "conversion_errors_before_success": errors,
        **details,
    }
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_model")
    parser.add_argument("output_glb")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--converter", default="auto", choices=["auto", "cadquery", "freecad", "passthrough"])
    parser.add_argument("--linear-tolerance", type=float, default=0.2)
    parser.add_argument("--angular-tolerance", type=float, default=0.1)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    manifest = convert_model(
        args.input_model,
        args.output_glb,
        args.manifest,
        converter=args.converter,
        linear_tolerance=args.linear_tolerance,
        angular_tolerance=args.angular_tolerance,
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
