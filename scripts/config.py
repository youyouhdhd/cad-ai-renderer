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


DEFAULT_PRODUCT_VIEW_SPECS: tuple[dict[str, Any], ...] = (
    {
        "view_id": "front",
        "label": "Front (+X) / 前视",
        "view_type": "principal",
        "axis": "+X",
        "azimuth": 0.0,
        "elevation": 0.0,
        "projection": "orthographic",
    },
    {
        "view_id": "right",
        "label": "Right (+Y) / 右视",
        "view_type": "principal",
        "axis": "+Y",
        "azimuth": 90.0,
        "elevation": 0.0,
        "projection": "orthographic",
    },
    {
        "view_id": "back",
        "label": "Back (-X) / 后视",
        "view_type": "principal",
        "axis": "-X",
        "azimuth": 180.0,
        "elevation": 0.0,
        "projection": "orthographic",
    },
    {
        "view_id": "left",
        "label": "Left (-Y) / 左视",
        "view_type": "principal",
        "axis": "-Y",
        "azimuth": 270.0,
        "elevation": 0.0,
        "projection": "orthographic",
    },
    {
        "view_id": "top",
        "label": "Top (+Z) / 俯视",
        "view_type": "principal",
        "axis": "+Z",
        "azimuth": 0.0,
        "elevation": 90.0,
        "projection": "orthographic",
    },
    {
        "view_id": "bottom",
        "label": "Bottom (-Z) / 仰视",
        "view_type": "principal",
        "axis": "-Z",
        "azimuth": 0.0,
        "elevation": -90.0,
        "projection": "orthographic",
    },
    {
        "view_id": "front_right_axonometric_upper",
        "label": "Front-right upper axonometric / 前右上轴测",
        "view_type": "axonometric",
        "axis": "+X +Y +Z",
        "azimuth": 45.0,
        "elevation": 30.0,
        "projection": "perspective",
    },
    {
        "view_id": "back_right_axonometric_upper",
        "label": "Back-right upper axonometric / 后右上轴测",
        "view_type": "axonometric",
        "axis": "-X +Y +Z",
        "azimuth": 135.0,
        "elevation": 30.0,
        "projection": "perspective",
    },
    {
        "view_id": "back_left_axonometric_upper",
        "label": "Back-left upper axonometric / 后左上轴测",
        "view_type": "axonometric",
        "axis": "-X -Y +Z",
        "azimuth": 225.0,
        "elevation": 30.0,
        "projection": "perspective",
    },
    {
        "view_id": "front_left_axonometric_upper",
        "label": "Front-left upper axonometric / 前左上轴测",
        "view_type": "axonometric",
        "axis": "+X -Y +Z",
        "azimuth": 315.0,
        "elevation": 30.0,
        "projection": "perspective",
    },
    {
        "view_id": "front_right_axonometric_lower",
        "label": "Front-right lower axonometric / 前右下轴测",
        "view_type": "axonometric",
        "axis": "+X +Y -Z",
        "azimuth": 45.0,
        "elevation": -30.0,
        "projection": "perspective",
    },
    {
        "view_id": "back_right_axonometric_lower",
        "label": "Back-right lower axonometric / 后右下轴测",
        "view_type": "axonometric",
        "axis": "-X +Y -Z",
        "azimuth": 135.0,
        "elevation": -30.0,
        "projection": "perspective",
    },
    {
        "view_id": "back_left_axonometric_lower",
        "label": "Back-left lower axonometric / 后左下轴测",
        "view_type": "axonometric",
        "axis": "-X -Y -Z",
        "azimuth": 225.0,
        "elevation": -30.0,
        "projection": "perspective",
    },
    {
        "view_id": "front_left_axonometric_lower",
        "label": "Front-left lower axonometric / 前左下轴测",
        "view_type": "axonometric",
        "axis": "+X -Y -Z",
        "azimuth": 315.0,
        "elevation": -30.0,
        "projection": "perspective",
    },
)


def product_view_specs(view_ids: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """Return the named product-view preset, optionally narrowed by view ID."""
    available = {str(item["view_id"]): item for item in DEFAULT_PRODUCT_VIEW_SPECS}
    selected = list(available) if view_ids is None else [str(item) for item in view_ids]
    unknown = [item for item in selected if item not in available]
    if unknown:
        raise ConfigError(f"camera.view_ids contains unsupported view IDs: {', '.join(unknown)}")
    return [deepcopy(available[item]) for item in selected]


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
        "view_set": "all",
        "view_ids": None,
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
        "view_grid_resolution": {"width": 768, "height": 768},
        "candidate_anchor_resolution": {"width": 1024, "height": 1024},
        "final_anchor_resolution": {"width": None, "height": None},
        "background_rgb": [0.94, 0.94, 0.94],
        "transparent_aux": False,
    },
    "generation": {
        "host_skill": "imagegen",
        "candidates": 4,
        "aspect_ratio": "1:1",
        "quality": "high",
        "target_resolution": "4k",
        "requested_native_size": "auto",
        "detail_level": "high",
        "output_format": "png",
        "max_retries": 1,
    },
    "final_output": {
        "width": None,
        "height": None,
        "format": "png",
        "resize_policy": "fit_pad",
        "allow_upscale": True,
    },
    "qa": {
        "min_geometry_score": 75.0,
        "min_visual_quality_score": 75.0,
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
ALLOWED_VIEW_SETS = {"all", "grid"}
ALLOWED_PROJECTIONS = {"perspective", "orthographic"}
ALLOWED_COLOR_MODES = {"auto", "original", "pseudo", "clay"}
ALLOWED_CONVERTERS = {"auto", "cadquery", "freecad", "passthrough"}
ALLOWED_AUX_BACKENDS = {"auto", "vtk"}
ALLOWED_OUTPUT_FORMATS = {"png", "jpeg", "webp"}
ALLOWED_QUALITIES = {"auto", "draft", "standard", "high"}
ALLOWED_HOST_SKILLS = {"imagegen", "auto"}
ALLOWED_TARGET_RESOLUTIONS = {"auto", "2k", "4k"}
ALLOWED_DETAIL_LEVELS = {"standard", "high"}
ALLOWED_ASPECT_RATIOS = {"auto", "1:1", "4:3", "3:4", "16:9", "9:16"}
ALLOWED_RESIZE_POLICIES = {"fit_pad"}
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
    _require_choice(generation.get("host_skill", "imagegen"), ALLOWED_HOST_SKILLS, "generation.host_skill")
    _require_choice(generation.get("aspect_ratio"), ALLOWED_ASPECT_RATIOS, "generation.aspect_ratio")
    _require_choice(generation.get("quality"), ALLOWED_QUALITIES, "generation.quality")
    _require_choice(generation.get("target_resolution", "4k"), ALLOWED_TARGET_RESOLUTIONS, "generation.target_resolution")
    _require_choice(generation.get("detail_level", "high"), ALLOWED_DETAIL_LEVELS, "generation.detail_level")
    _require_choice(generation.get("output_format"), ALLOWED_OUTPUT_FORMATS, "generation.output_format")
    requested_native_size = str(generation.get("requested_native_size", "auto"))
    if requested_native_size != "auto":
        try:
            native_width, native_height = [int(item) for item in requested_native_size.lower().split("x", 1)]
        except (TypeError, ValueError):
            raise ConfigError("generation.requested_native_size must be 'auto' or WIDTHxHEIGHT") from None
        if min(native_width, native_height) < 256 or max(native_width, native_height) > 8192:
            raise ConfigError("generation.requested_native_size dimensions must be between 256 and 8192")
    if int(generation.get("max_retries", 1)) not in {0, 1}:
        raise ConfigError("generation.max_retries must be 0 or 1")

    camera = cfg["camera"]
    _require_choice(camera.get("mode"), ALLOWED_CAMERA_MODES, "camera.mode")
    _require_choice(camera.get("view_set", "all"), ALLOWED_VIEW_SETS, "camera.view_set")
    view_ids = camera.get("view_ids")
    if view_ids is not None:
        if not isinstance(view_ids, list) or not view_ids or not all(isinstance(item, str) for item in view_ids):
            raise ConfigError("camera.view_ids must be a non-empty list of strings when supplied")
        product_view_specs(view_ids)
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
    for key in ("view_grid_resolution", "candidate_anchor_resolution", "final_anchor_resolution"):
        resolution = render.get(key)
        if not isinstance(resolution, Mapping):
            raise ConfigError(f"render.{key} must contain width and height")
        if key == "final_anchor_resolution" and resolution.get("width") is None and resolution.get("height") is None:
            continue
        if bool(resolution.get("width")) != bool(resolution.get("height")):
            raise ConfigError(f"render.{key}.width and height must be supplied together")
        for axis in ("width", "height"):
            value = int(resolution.get(axis, 0))
            if value < 256 or value > 4096:
                raise ConfigError(f"render.{key}.{axis} must be between 256 and 4096")
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
    min_visual = float(qa.get("min_visual_quality_score", 75.0))
    if not 0.0 <= min_visual <= 100.0:
        raise ConfigError("qa.min_visual_quality_score must be between 0 and 100")
    if float(qa.get("max_edge_distance_px", 18.0)) <= 0:
        raise ConfigError("qa.max_edge_distance_px must be greater than 0")

    final_output = cfg["final_output"]
    width = final_output.get("width")
    height = final_output.get("height")
    if bool(width) != bool(height):
        raise ConfigError("final_output.width and final_output.height must be supplied together")
    if width is not None:
        if not 256 <= int(width) <= 8192 or not 256 <= int(height) <= 8192:
            raise ConfigError("final_output dimensions must be between 256 and 8192")
    _require_choice(final_output.get("format", "png"), ALLOWED_OUTPUT_FORMATS, "final_output.format")
    _require_choice(
        final_output.get("resize_policy", "fit_pad"),
        ALLOWED_RESIZE_POLICIES,
        "final_output.resize_policy",
    )

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
