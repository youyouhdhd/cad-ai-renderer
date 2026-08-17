#!/usr/bin/env python3
"""Model-neutral configuration loading for cad-ai-renderer.

A project YAML is optional. The normal skill flow builds the same structure from
conversation attachments and user intent, then writes a resolved YAML only for
reproducibility.
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Run through scripts/run.py to use the managed environment.") from exc


DEFAULT_CONFIG: dict[str, Any] = {
    "project": {
        "name": "cad-ai-render",
        "input_model": None,
        "output_dir": "./output",
        "description": "",
        "references": [],
    },
    "camera": {
        "mode": "auto",
        "projection": "perspective",
        "azimuth": 35.0,
        "elevation": 22.0,
        "roll": 0.0,
        "fov_deg": 45.0,
        "framing": 0.82,
        "target": None,
        "position": None,
        "up": [0.0, 0.0, 1.0],
        "view_grid_azimuths": [0, 45, 90, 135, 180, 225, 270, 315],
        "view_grid_elevations": [15, 30],
    },
    "geometry": {
        "converter": "auto",
        "linear_tolerance": 0.2,
        "angular_tolerance": 0.1,
        "color_mode": "auto",
        "anchor_mode": "balanced",
        "up_axis": "z",
        "repair": True,
    },
    "render": {
        "aux_backend": "auto",
        "width": 1024,
        "height": 1024,
        "background_rgb": [0.94, 0.94, 0.94],
        "transparent_aux": False,
    },
    "generation": {
        "candidates": 4,
        "aspect_ratio": "1:1",
        "quality": "high",
        "output_format": "png",
        "max_retries": 1,
    },
    "qa": {
        "min_geometry_score": 75.0,
        "local_weight": 0.35,
        "visual_weight": 0.65,
        "max_edge_distance_px": 18.0,
        "retry_on_geometry_drift": True,
    },
    "comfyui": {
        "enabled": False,
        "server_url": "http://127.0.0.1:8188",
        "workflow": None,
        "timeout_seconds": 900,
    },
}

ALLOWED_ANCHOR_MODES = {"compact", "balanced", "max_geometry"}
ALLOWED_CAMERA_MODES = {"auto", "reference", "manual"}
ALLOWED_PROJECTIONS = {"perspective", "orthographic"}
ALLOWED_COLOR_MODES = {"auto", "original", "pseudo", "clay"}
ALLOWED_CONVERTERS = {"auto", "cadquery", "freecad", "passthrough"}
ALLOWED_AUX_BACKENDS = {"auto", "vtk"}
ALLOWED_OUTPUT_FORMATS = {"png", "jpeg", "webp"}
ALLOWED_QUALITIES = {"auto", "draft", "standard", "high"}
ALLOWED_ASPECT_RATIOS = {"auto", "1:1", "4:3", "3:4", "16:9", "9:16"}
ALLOWED_REFERENCE_ROLES = {
    "camera",
    "composition",
    "material",
    "color",
    "lighting",
    "style",
    "environment",
    "detail",
    "mixed",
}


class ConfigError(ValueError):
    """Raised for invalid project configuration."""


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def _expand_path(value: str | os.PathLike[str] | None, base_dir: Path) -> str | None:
    if value is None:
        return None
    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    path = Path(expanded)
    if not path.is_absolute():
        path = base_dir / path
    return str(path.resolve())


def _require_choice(value: Any, allowed: Iterable[Any], label: str) -> None:
    if value not in allowed:
        choices = ", ".join(sorted(str(v) for v in allowed))
        raise ConfigError(f"{label} must be one of: {choices}; got {value!r}")


def normalize_references(refs: Any, base_dir: Path) -> list[dict[str, Any]]:
    """Normalize references without requiring users to author role metadata."""
    if refs is None:
        return []
    if not isinstance(refs, list):
        raise ConfigError("project.references must be a list")
    normalized: list[dict[str, Any]] = []
    for index, ref in enumerate(refs):
        if isinstance(ref, (str, os.PathLike)):
            item = {"path": str(ref), "roles": ["mixed"], "notes": "", "source": "attachment"}
        elif isinstance(ref, Mapping):
            item = dict(ref)
        else:
            raise ConfigError(f"project.references[{index}] must be a path or object")
        if not item.get("path"):
            raise ConfigError(f"project.references[{index}].path is required")
        item["path"] = _expand_path(str(item["path"]), base_dir)
        roles = item.get("roles", ["mixed"])
        if isinstance(roles, str):
            roles = [roles]
        if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
            raise ConfigError(f"project.references[{index}].roles must be a list of strings")
        roles = [role.strip().lower() for role in roles if role.strip()]
        roles = roles or ["mixed"]
        unknown = sorted(set(roles) - ALLOWED_REFERENCE_ROLES)
        if unknown:
            raise ConfigError(
                f"project.references[{index}].roles contains unsupported roles: {', '.join(unknown)}"
            )
        item["roles"] = roles
        item.setdefault("notes", "")
        item.setdefault("source", "attachment")
        normalized.append(item)
    return normalized


def build_direct_config(
    input_model: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    description: str = "",
    references: Sequence[str | os.PathLike[str] | Mapping[str, Any]] | None = None,
    name: str | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a resolved config from attachment paths and conversation intent."""
    base_dir = Path.cwd().resolve()
    raw: dict[str, Any] = {
        "project": {
            "name": name or Path(input_model).stem,
            "input_model": str(input_model),
            "output_dir": str(output_dir),
            "description": description,
            "references": list(references or []),
        }
    }
    if overrides:
        raw = _deep_merge(raw, overrides)
    cfg = _deep_merge(DEFAULT_CONFIG, raw)
    cfg["project"]["input_model"] = _expand_path(cfg["project"].get("input_model"), base_dir)
    cfg["project"]["output_dir"] = _expand_path(cfg["project"].get("output_dir"), base_dir)
    cfg["project"]["references"] = normalize_references(cfg["project"].get("references"), base_dir)
    workflow = cfg["comfyui"].get("workflow")
    cfg["comfyui"]["workflow"] = _expand_path(workflow, base_dir) if workflow else None
    cfg["_meta"] = {"config_path": None, "config_dir": str(base_dir), "source": "direct_inputs"}
    validate_config(cfg)
    return cfg


def load_config(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load the optional project YAML used for reproducible or advanced runs."""
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(f"Project file does not exist: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ConfigError("Project YAML root must be an object")
    cfg = _deep_merge(DEFAULT_CONFIG, raw)
    base_dir = config_path.parent
    project = cfg["project"]
    project["input_model"] = _expand_path(project.get("input_model"), base_dir)
    project["output_dir"] = _expand_path(project.get("output_dir"), base_dir)
    project["references"] = normalize_references(project.get("references"), base_dir)
    workflow = cfg["comfyui"].get("workflow")
    cfg["comfyui"]["workflow"] = _expand_path(workflow, base_dir) if workflow else None
    cfg["_meta"] = {
        "config_path": str(config_path),
        "config_dir": str(base_dir),
        "source": "project_yaml",
    }
    validate_config(cfg)
    return cfg


def validate_config(cfg: Mapping[str, Any], require_files: bool = True) -> None:
    for section in DEFAULT_CONFIG:
        if section not in cfg or not isinstance(cfg[section], Mapping):
            raise ConfigError(f"Missing or invalid section: {section}")

    project = cfg["project"]
    model_path = project.get("input_model")
    if not model_path:
        raise ConfigError("project.input_model is required")
    if require_files and not Path(str(model_path)).exists():
        raise ConfigError(f"Input model does not exist: {model_path}")
    for ref in project.get("references", []):
        if require_files and not Path(str(ref["path"])).exists():
            raise ConfigError(f"Reference image does not exist: {ref['path']}")

    generation = cfg["generation"]
    candidates = int(generation.get("candidates", 4))
    if not 1 <= candidates <= 10:
        raise ConfigError("generation.candidates must be between 1 and 10")
    _require_choice(generation.get("aspect_ratio"), ALLOWED_ASPECT_RATIOS, "generation.aspect_ratio")
    _require_choice(generation.get("quality"), ALLOWED_QUALITIES, "generation.quality")
    _require_choice(generation.get("output_format"), ALLOWED_OUTPUT_FORMATS, "generation.output_format")
    if int(generation.get("max_retries", 1)) not in {0, 1}:
        raise ConfigError("generation.max_retries must be 0 or 1")

    camera = cfg["camera"]
    _require_choice(camera.get("mode"), ALLOWED_CAMERA_MODES, "camera.mode")
    _require_choice(camera.get("projection"), ALLOWED_PROJECTIONS, "camera.projection")
    if not 1.0 <= float(camera.get("fov_deg", 45)) <= 150.0:
        raise ConfigError("camera.fov_deg must be between 1 and 150")
    if not 0.2 <= float(camera.get("framing", 0.82)) <= 0.98:
        raise ConfigError("camera.framing must be between 0.2 and 0.98")
    if camera.get("mode") == "manual":
        position = camera.get("position")
        target = camera.get("target")
        if bool(position) != bool(target):
            raise ConfigError("manual camera requires both camera.position and camera.target, or neither")

    geometry = cfg["geometry"]
    _require_choice(geometry.get("converter"), ALLOWED_CONVERTERS, "geometry.converter")
    _require_choice(geometry.get("color_mode"), ALLOWED_COLOR_MODES, "geometry.color_mode")
    _require_choice(geometry.get("anchor_mode"), ALLOWED_ANCHOR_MODES, "geometry.anchor_mode")
    if str(geometry.get("up_axis", "z")).lower() != "z":
        raise ConfigError("geometry.up_axis currently supports only z")
    if float(geometry.get("linear_tolerance", 0.2)) <= 0:
        raise ConfigError("geometry.linear_tolerance must be greater than 0")
    if float(geometry.get("angular_tolerance", 0.1)) <= 0:
        raise ConfigError("geometry.angular_tolerance must be greater than 0")

    render = cfg["render"]
    _require_choice(render.get("aux_backend"), ALLOWED_AUX_BACKENDS, "render.aux_backend")
    for key in ("width", "height"):
        value = int(render.get(key, 1024))
        if value < 256 or value > 4096:
            raise ConfigError(f"render.{key} must be between 256 and 4096")
    background_rgb = render.get("background_rgb")
    if (
        not isinstance(background_rgb, (list, tuple))
        or len(background_rgb) != 3
        or any(not 0.0 <= float(channel) <= 1.0 for channel in background_rgb)
    ):
        raise ConfigError("render.background_rgb must contain exactly three values in the 0-1 range")

    qa = cfg["qa"]
    local_weight = float(qa.get("local_weight", 0.35))
    visual_weight = float(qa.get("visual_weight", 0.65))
    if not 0.0 <= local_weight <= 1.0 or not 0.0 <= visual_weight <= 1.0:
        raise ConfigError("qa.local_weight and qa.visual_weight must each be between 0 and 1")
    if abs((local_weight + visual_weight) - 1.0) > 1e-6:
        raise ConfigError("qa.local_weight + qa.visual_weight must equal 1.0")
    min_geometry = float(qa.get("min_geometry_score", 75.0))
    if not 0.0 <= min_geometry <= 100.0:
        raise ConfigError("qa.min_geometry_score must be between 0 and 100")
    if float(qa.get("max_edge_distance_px", 18.0)) <= 0:
        raise ConfigError("qa.max_edge_distance_px must be greater than 0")

    comfyui = cfg["comfyui"]
    if bool(comfyui.get("enabled")):
        workflow = comfyui.get("workflow")
        if not workflow:
            raise ConfigError("comfyui.workflow is required when comfyui.enabled is true")
        if require_files and not Path(str(workflow)).exists():
            raise ConfigError(f"ComfyUI workflow does not exist: {workflow}")
    if int(comfyui.get("timeout_seconds", 900)) < 30:
        raise ConfigError("comfyui.timeout_seconds must be at least 30")


def dump_resolved_config(cfg: Mapping[str, Any], path: str | os.PathLike[str]) -> None:
    serializable = {key: value for key, value in cfg.items() if key != "_meta"}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(serializable, sort_keys=False, allow_unicode=True), encoding="utf-8")


def config_fingerprint(cfg: Mapping[str, Any]) -> str:
    serializable = {key: value for key, value in cfg.items() if key != "_meta"}
    raw = json.dumps(serializable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
