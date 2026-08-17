#!/usr/bin/env python3
"""Check the isolated Python environment, local CAD dependencies, and input paths."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from config import ConfigError, build_direct_config, load_config
from input_discovery import InputDiscoveryError, discover_inputs

REQUIRED_MODULES = {
    "yaml": "PyYAML",
    "numpy": "numpy",
    "PIL": "Pillow",
    "cv2": "opencv-python-headless",
    "requests": "requests",
    "cadquery": "cadquery",
    "OCP": "cadquery/OCP",
    "vtk": "vtk",
    "trimesh": "trimesh",
}


def _module_check(name: str, package: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(name)
        version = getattr(module, "__version__", None)
        return {"name": name, "package": package, "ok": True, "version": version}
    except Exception as exc:
        return {"name": name, "package": package, "ok": False, "error": str(exc)}


def run_preflight(
    project_path: str | Path | None = None,
    *,
    inputs: list[str] | None = None,
    model: str | None = None,
    references: list[str] | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    managed_venv = os.environ.get("CAD_AI_RENDERER_MANAGED_VENV")
    report: dict[str, Any] = {
        "python": {
            "version": sys.version,
            "executable": sys.executable,
            "ok": sys.version_info >= (3, 10),
            "inside_virtualenv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
            "managed_venv": managed_venv,
            "managed_venv_mode": os.environ.get("CAD_AI_RENDERER_VENV_MODE"),
        },
        "modules": [_module_check(name, package) for name, package in REQUIRED_MODULES.items()],
        "executables": {
            "FreeCADCmd": shutil.which("FreeCADCmd") or shutil.which("freecadcmd"),
            "blender": shutil.which("blender"),
        },
        "project": None,
        "host_image_generation": {
            "raw_api_required": False,
            "note": "Availability is checked by the host skill runtime, not by local Python.",
        },
        "comfyui": None,
        "errors": [],
        "warnings": [],
    }
    if not report["python"]["ok"]:
        report["errors"].append("Python 3.10 or later is required")
    if not report["python"]["inside_virtualenv"]:
        report["warnings"].append("Not running inside a virtual environment; invoke through scripts/run.py")
    if not managed_venv:
        report["warnings"].append("The dedicated cad-ai-renderer launcher was not used")
    for item in report["modules"]:
        if not item["ok"]:
            report["errors"].append(f"Missing required module {item['name']} ({item['package']})")

    config = None
    try:
        if project_path:
            config = load_config(project_path)
            discovery = {
                "model": config["project"]["input_model"],
                "references": config["project"]["references"],
                "source": "project_yaml",
            }
        elif inputs or model:
            discovery = discover_inputs(inputs or [], model, references or [])
            destination = output_dir or str((Path.cwd() / "cad-ai-render-output" / Path(discovery["model"]).stem).resolve())
            config = build_direct_config(
                discovery["model"],
                destination,
                references=discovery["references"],
            )
        else:
            discovery = None
        if config:
            destination = Path(config["project"]["output_dir"])
            destination.mkdir(parents=True, exist_ok=True)
            probe = destination / ".cad_ai_renderer_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            report["project"] = {
                "ok": True,
                "input_model": config["project"]["input_model"],
                "output_dir": str(destination),
                "reference_count": len(config["project"]["references"]),
                "discovery": discovery,
            }
    except (ConfigError, InputDiscoveryError, FileNotFoundError, OSError) as exc:
        report["project"] = {"ok": False, "error": str(exc)}
        report["errors"].append(f"Input validation failed: {exc}")

    if config and config["comfyui"]["enabled"]:
        try:
            import requests

            url = config["comfyui"]["server_url"].rstrip("/")
            response = requests.get(f"{url}/system_stats", timeout=5)
            report["comfyui"] = {"url": url, "ok": response.status_code < 400}
            if response.status_code >= 400:
                report["warnings"].append(f"ComfyUI returned HTTP {response.status_code}")
        except Exception as exc:
            report["comfyui"] = {"ok": False, "error": str(exc)}
            report["warnings"].append("ComfyUI is enabled but could not be reached")

    if not report["executables"]["FreeCADCmd"]:
        report["warnings"].append("FreeCADCmd is unavailable; CadQuery/OCP remains the primary STEP path")
    if not report["executables"]["blender"]:
        report["warnings"].append("Blender is unavailable; VTK offscreen auxiliary rendering remains available")
    report["ok"] = not report["errors"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project")
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--model")
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("--output-dir")
    parser.add_argument("--report")
    args = parser.parse_args()
    report = run_preflight(
        args.project,
        inputs=args.input,
        model=args.model,
        references=args.reference,
        output_dir=args.output_dir,
    )
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
