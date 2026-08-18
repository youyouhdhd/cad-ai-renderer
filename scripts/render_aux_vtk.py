#!/usr/bin/env python3
"""Render deterministic geometry anchors from GLB with VTK offscreen rendering."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import cv2
import numpy as np
from PIL import Image, ImageOps

from image_utils import make_contact_sheet

try:
    import vtk
    from vtk.util.numpy_support import vtk_to_numpy
except ImportError as exc:  # pragma: no cover
    raise SystemExit("VTK is required. Install with: pip install vtk") from exc


DEFAULT_PALETTE = [
    (0.78, 0.25, 0.20),
    (0.16, 0.43, 0.72),
    (0.20, 0.61, 0.43),
    (0.88, 0.58, 0.16),
    (0.50, 0.32, 0.70),
    (0.14, 0.62, 0.68),
    (0.75, 0.39, 0.60),
    (0.48, 0.52, 0.18),
    (0.70, 0.45, 0.24),
    (0.32, 0.36, 0.62),
]


class RenderError(RuntimeError):
    pass


def _normalize(vector: np.ndarray, fallback: np.ndarray | None = None) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm < 1e-12:
        if fallback is None:
            raise ValueError("Cannot normalize zero vector")
        return fallback.astype(np.float64)
    return vector / norm


def _bounds_corners(bounds: Sequence[float]) -> np.ndarray:
    xmin, xmax, ymin, ymax, zmin, zmax = [float(value) for value in bounds]
    return np.asarray(
        [
            [x, y, z]
            for x in (xmin, xmax)
            for y in (ymin, ymax)
            for z in (zmin, zmax)
        ],
        dtype=np.float64,
    )


def _unique_id_color(index: int) -> tuple[float, float, float]:
    value = index + 1
    r = ((value * 73) % 251 + 1) / 255.0
    g = ((value * 151) % 251 + 1) / 255.0
    b = ((value * 199) % 251 + 1) / 255.0
    return r, g, b


def _write_png(array: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array).save(path)


class VTKAnchorRenderer:
    def __init__(
        self,
        glb_path: str | Path,
        width: int = 1024,
        height: int = 1024,
        background_rgb: Sequence[float] = (0.94, 0.94, 0.94),
        source_has_useful_colors: bool = True,
        color_mode: str = "auto",
        palette: Sequence[Sequence[float]] | None = None,
    ) -> None:
        self.glb_path = Path(glb_path).expanduser().resolve()
        if not self.glb_path.exists():
            raise FileNotFoundError(self.glb_path)
        self.width = int(width)
        self.height = int(height)
        self.background_rgb = tuple(float(value) for value in background_rgb)
        self.source_has_useful_colors = bool(source_has_useful_colors)
        self.color_mode = color_mode
        self.palette = [tuple(float(v) for v in color[:3]) for color in (palette or DEFAULT_PALETTE)]

        self.window = vtk.vtkRenderWindow()
        self.window.SetOffScreenRendering(1)
        self.window.SetSize(self.width, self.height)
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(*self.background_rgb)
        self.window.AddRenderer(self.renderer)
        self.importer = vtk.vtkGLTFImporter()
        self.importer.SetFileName(str(self.glb_path))
        self.importer.SetRenderWindow(self.window)
        try:
            self.importer.Update()
        except Exception as exc:
            raise RenderError(f"VTK failed to import GLB: {self.glb_path}") from exc

        self.actors = self._collect_actors()
        if not self.actors:
            raise RenderError(f"No visible polygon actors were imported from {self.glb_path}")
        self.bounds = tuple(float(value) for value in self.renderer.ComputeVisiblePropBounds())
        if len(self.bounds) != 6 or any(not math.isfinite(value) for value in self.bounds):
            raise RenderError("Imported model has invalid bounds")
        self.original_states = self._save_actor_states()
        self._setup_lights()
        self.camera_spec: dict[str, Any] | None = None

    def _collect_actors(self) -> list[Any]:
        actors: list[Any] = []
        collection = self.renderer.GetActors()
        collection.InitTraversal()
        while True:
            actor = collection.GetNextActor()
            if actor is None:
                break
            mapper = actor.GetMapper()
            if mapper is None:
                continue
            try:
                mapper.Update()
                data = mapper.GetInput()
                if data is None or data.GetNumberOfPoints() == 0:
                    continue
            except Exception:
                pass
            actors.append(actor)
        return actors

    def _save_actor_states(self) -> list[dict[str, Any]]:
        states: list[dict[str, Any]] = []
        for actor in self.actors:
            prop_copy = vtk.vtkProperty()
            prop_copy.DeepCopy(actor.GetProperty())
            states.append(
                {
                    "property": prop_copy,
                    "texture": actor.GetTexture(),
                    "visibility": actor.GetVisibility(),
                }
            )
        return states

    def restore_original_style(self) -> None:
        for actor, state in zip(self.actors, self.original_states):
            actor.GetProperty().DeepCopy(state["property"])
            actor.SetTexture(state["texture"])
            actor.SetVisibility(state["visibility"])

    def _clear_material_textures(self, actor: Any) -> None:
        actor.SetTexture(None)
        prop = actor.GetProperty()
        if hasattr(prop, "RemoveAllTextures"):
            try:
                prop.RemoveAllTextures()
            except Exception:
                pass

    def _set_actor_material(
        self,
        actor: Any,
        color: Sequence[float],
        flat: bool = False,
        opacity: float = 1.0,
    ) -> None:
        self._clear_material_textures(actor)
        prop = actor.GetProperty()
        rgb = tuple(float(value) for value in color[:3])
        prop.SetColor(*rgb)
        if hasattr(prop, "SetBaseColor"):
            prop.SetBaseColor(*rgb)
        prop.SetOpacity(float(opacity))
        if flat:
            prop.SetInterpolationToFlat()
            prop.SetAmbient(1.0)
            prop.SetDiffuse(0.0)
            prop.SetSpecular(0.0)
        else:
            prop.SetInterpolationToPhong()
            prop.SetAmbient(0.15)
            prop.SetDiffuse(0.82)
            prop.SetSpecular(0.25)
            prop.SetSpecularPower(35.0)

    def apply_preview_style(self) -> str:
        use_original = self.color_mode == "original" or (
            self.color_mode == "auto" and self.source_has_useful_colors
        )
        if use_original:
            self.restore_original_style()
            return "original"
        if self.color_mode == "clay":
            for actor in self.actors:
                self._set_actor_material(actor, (0.72, 0.73, 0.75))
            return "clay"
        for index, actor in enumerate(self.actors):
            self._set_actor_material(actor, self.palette[index % len(self.palette)])
        return "pseudo"

    def apply_clay_style(self) -> None:
        for actor in self.actors:
            self._set_actor_material(actor, (0.70, 0.72, 0.75))

    def apply_part_id_style(self) -> list[dict[str, Any]]:
        mapping: list[dict[str, Any]] = []
        for index, actor in enumerate(self.actors):
            color = _unique_id_color(index)
            self._set_actor_material(actor, color, flat=True)
            mapping.append(
                {
                    "actor_index": index,
                    "rgb": [int(round(channel * 255)) for channel in color],
                }
            )
        return mapping

    def _setup_lights(self) -> None:
        self.renderer.RemoveAllLights()
        corners = _bounds_corners(self.bounds)
        center = corners.mean(axis=0)
        diagonal = float(np.linalg.norm(corners.max(axis=0) - corners.min(axis=0)))
        diagonal = max(diagonal, 1.0)
        specs = [
            (center + np.array([1.8, -2.2, 2.8]) * diagonal, 0.95),
            (center + np.array([-2.0, -0.5, 1.2]) * diagonal, 0.45),
            (center + np.array([0.3, 2.2, 2.0]) * diagonal, 0.60),
        ]
        for position, intensity in specs:
            light = vtk.vtkLight()
            light.SetLightTypeToSceneLight()
            light.SetPosition(*[float(v) for v in position])
            light.SetFocalPoint(*[float(v) for v in center])
            light.SetColor(1.0, 1.0, 1.0)
            light.SetIntensity(float(intensity))
            light.SetPositional(False)
            self.renderer.AddLight(light)

    def set_camera(self, spec: dict[str, Any]) -> dict[str, Any]:
        camera = self.renderer.GetActiveCamera()
        projection = str(spec.get("projection", "perspective"))
        fov_deg = float(spec.get("fov_deg", 45.0))
        framing = float(spec.get("framing", 0.82))
        roll = float(spec.get("roll", 0.0))
        corners = _bounds_corners(self.bounds)
        center = corners.mean(axis=0)
        aspect = self.width / max(self.height, 1)

        explicit_position = spec.get("position")
        explicit_target = spec.get("target")
        if explicit_position is not None and explicit_target is not None:
            position = np.asarray(explicit_position, dtype=np.float64)
            target = np.asarray(explicit_target, dtype=np.float64)
            forward = _normalize(target - position)
            view_up = np.asarray(spec.get("up", [0, 0, 1]), dtype=np.float64)
            if abs(float(np.dot(_normalize(view_up), forward))) > 0.98:
                view_up = np.asarray([0, 1, 0], dtype=np.float64)
        else:
            azimuth = math.radians(float(spec.get("azimuth", 35.0)))
            elevation = math.radians(float(spec.get("elevation", 22.0)))
            outward = np.asarray(
                [
                    math.cos(elevation) * math.cos(azimuth),
                    math.cos(elevation) * math.sin(azimuth),
                    math.sin(elevation),
                ],
                dtype=np.float64,
            )
            forward = -_normalize(outward)
            world_up = np.asarray(spec.get("up", [0, 0, 1]), dtype=np.float64)
            if abs(float(np.dot(_normalize(world_up), forward))) > 0.98:
                world_up = np.asarray([0, 1, 0], dtype=np.float64)
            right = _normalize(np.cross(forward, world_up))
            view_up = _normalize(np.cross(right, forward))
            target = center
            rel = corners - target
            x_values = rel @ right
            y_values = rel @ view_up
            z_values = rel @ forward
            if projection == "orthographic":
                half_height = max(float(np.max(np.abs(y_values))), float(np.max(np.abs(x_values))) / aspect)
                parallel_scale = max(half_height / max(framing, 1e-3), 1e-6)
                distance = max(float(np.linalg.norm(corners.max(axis=0) - corners.min(axis=0))) * 2.0, 1.0)
                position = target - forward * distance
                camera.ParallelProjectionOn()
                camera.SetParallelScale(parallel_scale)
            else:
                camera.ParallelProjectionOff()
                vfov = math.radians(fov_deg)
                tan_v = math.tan(vfov / 2.0)
                tan_h = tan_v * aspect
                required_x = np.abs(x_values) / max(tan_h * framing, 1e-6) - z_values
                required_y = np.abs(y_values) / max(tan_v * framing, 1e-6) - z_values
                distance = max(float(np.max(required_x)), float(np.max(required_y)), 1e-3)
                diagonal = float(np.linalg.norm(corners.max(axis=0) - corners.min(axis=0)))
                distance += max(diagonal * 0.03, 1e-4)
                position = target - forward * distance

        camera.SetPosition(*[float(v) for v in position])
        camera.SetFocalPoint(*[float(v) for v in target])
        camera.SetViewUp(*[float(v) for v in view_up])
        camera.SetViewAngle(fov_deg)
        if projection == "orthographic":
            camera.ParallelProjectionOn()
        else:
            camera.ParallelProjectionOff()
        if roll:
            camera.Roll(roll)
        self.renderer.ResetCameraClippingRange(self.bounds)
        near_value, far_value = camera.GetClippingRange()
        near_value = max(float(near_value), 1e-5)
        far_value = max(float(far_value), near_value + 1e-4)
        camera.SetClippingRange(near_value, far_value)
        self.camera_spec = {
            "projection": projection,
            "position": [float(v) for v in camera.GetPosition()],
            "target": [float(v) for v in camera.GetFocalPoint()],
            "up": [float(v) for v in camera.GetViewUp()],
            "azimuth": float(spec.get("azimuth", 35.0)),
            "elevation": float(spec.get("elevation", 22.0)),
            "roll": roll,
            "fov_deg": fov_deg,
            "framing": framing,
            "parallel_scale": float(camera.GetParallelScale()),
            "clipping_range": [near_value, far_value],
            "image_size": [self.width, self.height],
            "model_bounds": list(self.bounds),
        }
        return dict(self.camera_spec)

    def _render(self) -> None:
        self.renderer.ResetCameraClippingRange(self.bounds)
        self.window.Render()

    def _capture_rgba(self) -> np.ndarray:
        self._render()
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(self.window)
        capture.SetInputBufferTypeToRGBA()
        capture.ReadFrontBufferOff()
        capture.Update()
        image = capture.GetOutput()
        width, height, _ = image.GetDimensions()
        array = vtk_to_numpy(image.GetPointData().GetScalars()).reshape(height, width, 4)
        return np.flipud(array).copy()

    def _capture_z(self) -> np.ndarray:
        self._render()
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(self.window)
        capture.SetInputBufferTypeToZBuffer()
        capture.ReadFrontBufferOff()
        capture.Update()
        image = capture.GetOutput()
        width, height, _ = image.GetDimensions()
        array = vtk_to_numpy(image.GetPointData().GetScalars()).reshape(height, width)
        return np.flipud(array).astype(np.float32, copy=True)

    def _linear_depth(self, z_buffer: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self.camera_spec is None:
            raise RenderError("Camera must be set before rendering depth")
        near_value, far_value = self.camera_spec["clipping_range"]
        valid = z_buffer < 0.999999
        if self.camera_spec["projection"] == "orthographic":
            linear = near_value + z_buffer * (far_value - near_value)
        else:
            z_ndc = 2.0 * z_buffer - 1.0
            denominator = far_value + near_value - z_ndc * (far_value - near_value)
            linear = (2.0 * near_value * far_value) / np.maximum(denominator, 1e-12)
        linear = linear.astype(np.float32)
        linear[~valid] = np.nan
        normalized = np.zeros_like(linear, dtype=np.float32)
        if np.any(valid):
            dmin = float(np.nanpercentile(linear, 0.5))
            dmax = float(np.nanpercentile(linear, 99.5))
            if dmax <= dmin:
                dmax = dmin + 1.0
            normalized[valid] = np.clip((dmax - linear[valid]) / (dmax - dmin), 0.0, 1.0)
        depth16 = np.round(normalized * 65535.0).astype(np.uint16)
        mask = (valid.astype(np.uint8) * 255)
        return linear, depth16, mask

    def _normals_from_depth(self, linear: np.ndarray, mask: np.ndarray) -> np.ndarray:
        if self.camera_spec is None:
            raise RenderError("Camera must be set before normal reconstruction")
        height, width = linear.shape
        yy, xx = np.mgrid[0:height, 0:width]
        x_ndc = 2.0 * (xx + 0.5) / width - 1.0
        y_ndc = 1.0 - 2.0 * (yy + 0.5) / height
        z = np.nan_to_num(linear, nan=0.0).astype(np.float64)
        aspect = width / max(height, 1)
        if self.camera_spec["projection"] == "orthographic":
            scale_y = float(self.camera_spec["parallel_scale"])
            x = x_ndc * scale_y * aspect
            y = y_ndc * scale_y
        else:
            tan_v = math.tan(math.radians(float(self.camera_spec["fov_deg"])) / 2.0)
            x = x_ndc * z * tan_v * aspect
            y = y_ndc * z * tan_v
        points = np.stack([x, y, z], axis=-1)
        dx = np.gradient(points, axis=1)
        dy = np.gradient(points, axis=0)
        normals = np.cross(dy, dx)
        lengths = np.linalg.norm(normals, axis=-1, keepdims=True)
        normals = normals / np.maximum(lengths, 1e-12)
        flip = normals[..., 2] < 0
        normals[flip] *= -1.0
        valid = mask > 0
        valid = cv2.erode(valid.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1).astype(bool)
        encoded = np.full((height, width, 3), 127, dtype=np.uint8)
        mapped = np.clip((normals * 0.5 + 0.5) * 255.0, 0, 255).astype(np.uint8)
        encoded[valid] = mapped[valid]
        return encoded

    def _lineart(self, depth16: np.ndarray, mask: np.ndarray, part_id: np.ndarray) -> np.ndarray:
        depth8 = np.round(depth16.astype(np.float32) / 257.0).astype(np.uint8)
        depth_blur = cv2.GaussianBlur(depth8, (5, 5), 0)
        depth_edges = cv2.Canny(depth_blur, 18, 55)
        mask_edges = cv2.morphologyEx(mask, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
        part_rgb = part_id[..., :3]
        part_edges = np.zeros(mask.shape, dtype=np.uint8)
        part_edges[:, 1:] |= np.any(part_rgb[:, 1:] != part_rgb[:, :-1], axis=-1).astype(np.uint8) * 255
        part_edges[1:, :] |= np.any(part_rgb[1:, :] != part_rgb[:-1, :], axis=-1).astype(np.uint8) * 255
        edges = np.maximum.reduce([depth_edges, mask_edges, part_edges])
        edges[mask == 0] = np.maximum(edges[mask == 0], mask_edges[mask == 0])
        edges = cv2.dilate(edges, np.ones((2, 2), np.uint8), iterations=1)
        lineart = np.full(mask.shape, 255, dtype=np.uint8)
        lineart[edges > 0] = 0
        return lineart

    def render_view_grid(
        self,
        output_dir: str | Path,
        base_spec: dict[str, Any],
        azimuths: Iterable[float] | None = None,
        elevations: Iterable[float] | None = None,
        view_specs: Sequence[Mapping[str, Any]] | None = None,
        thumb_size: int = 320,
    ) -> dict[str, Any]:
        output = Path(output_dir)
        view_dir = output / "views"
        view_dir.mkdir(parents=True, exist_ok=True)
        original_size = (self.width, self.height)
        self.width = self.height = int(thumb_size)
        self.window.SetSize(self.width, self.height)
        preview_mode = self.apply_preview_style()
        records: list[dict[str, Any]] = []
        paths: list[Path] = []
        labels: list[str] = []
        if view_specs is None:
            planned_specs = [
                {
                    "view_id": f"V{index:02d}",
                    "label": f"V{index:02d}  az {float(azimuth):g}  el {float(elevation):g}",
                    "view_type": "grid",
                    "azimuth": float(azimuth),
                    "elevation": float(elevation),
                }
                for index, (elevation, azimuth) in enumerate(
                    ((elevation, azimuth) for elevation in (elevations or []) for azimuth in (azimuths or [])),
                    start=1,
                )
            ]
        else:
            planned_specs = [dict(item) for item in view_specs]

        for index, planned in enumerate(planned_specs, start=1):
            view_id = str(planned.get("view_id") or f"V{index:02d}")
            view_label = str(planned.get("label") or view_id)
            spec = dict(base_spec)
            spec.update(
                {
                    key: planned[key]
                    for key in ("azimuth", "elevation", "projection", "fov_deg", "framing", "roll", "target", "position", "up")
                    if planned.get(key) is not None
                }
            )
            camera_info = self.set_camera(spec)
            image = self._capture_rgba()[..., :3]
            safe_view_id = "".join(char if char.isalnum() or char in "-_" else "_" for char in view_id)
            file_stem = safe_view_id or f"{index:02d}"
            path = view_dir / f"view_{file_stem}.png"
            _write_png(image, path)
            records.append(
                {
                    "view_id": view_id,
                    "label": view_label,
                    "view_type": str(planned.get("view_type", "grid")),
                    "axis": planned.get("axis"),
                    "path": str(path),
                    "azimuth": float(spec.get("azimuth", 35.0)),
                    "elevation": float(spec.get("elevation", 22.0)),
                    "projection": str(spec.get("projection", "perspective")),
                    "camera": camera_info,
                }
            )
            paths.append(path)
            labels.append(view_label)
        make_contact_sheet(
            paths,
            output / "view_grid.png",
            labels=labels,
            columns=min(4, len(paths)),
            cell_size=(thumb_size, thumb_size),
            label_height=38,
        )
        (output / "view_grid.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        self.width, self.height = original_size
        self.window.SetSize(self.width, self.height)
        return {
            "preview_color_mode": preview_mode,
            "view_grid": str(output / "view_grid.png"),
            "view_grid_json": str(output / "view_grid.json"),
            "views": records,
        }

    def render_auxiliary_set(self, output_dir: str | Path, camera_spec: dict[str, Any]) -> dict[str, Any]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        self.window.SetSize(self.width, self.height)
        camera_info = self.set_camera(camera_spec)

        preview_mode = self.apply_preview_style()
        color_preview = self._capture_rgba()[..., :3]
        _write_png(color_preview, output / "color_preview.png")

        self.apply_clay_style()
        clay = self._capture_rgba()[..., :3]
        _write_png(clay, output / "clay.png")
        z_buffer = self._capture_z()
        linear_depth, depth16, mask = self._linear_depth(z_buffer)
        _write_png(depth16, output / "depth.png")
        _write_png(mask, output / "mask.png")

        part_mapping = self.apply_part_id_style()
        part_id = self._capture_rgba()[..., :3]
        part_id[mask == 0] = 0
        _write_png(part_id, output / "part_id.png")

        normals = self._normals_from_depth(linear_depth, mask)
        _write_png(normals, output / "normal.png")
        lineart = self._lineart(depth16, mask, part_id)
        _write_png(lineart, output / "lineart.png")

        camera_path = output / "camera.json"
        camera_path.write_text(json.dumps(camera_info, indent=2), encoding="utf-8")
        mapping_path = output / "part_id_map.json"
        mapping_path.write_text(json.dumps(part_mapping, indent=2), encoding="utf-8")
        manifest = {
            "backend": "vtk",
            "preview_color_mode": preview_mode,
            "actor_count": len(self.actors),
            "camera": camera_info,
            "files": {
                "color_preview": str(output / "color_preview.png"),
                "clay": str(output / "clay.png"),
                "lineart": str(output / "lineart.png"),
                "mask": str(output / "mask.png"),
                "normal": str(output / "normal.png"),
                "depth": str(output / "depth.png"),
                "part_id": str(output / "part_id.png"),
                "camera": str(camera_path),
                "part_id_map": str(mapping_path),
            },
        }
        (output / "aux_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def close(self) -> None:
        try:
            self.window.Finalize()
        except Exception:
            pass


def render_auxiliary(
    glb_path: str | Path,
    output_dir: str | Path,
    camera_spec: dict[str, Any],
    width: int = 1024,
    height: int = 1024,
    background_rgb: Sequence[float] = (0.94, 0.94, 0.94),
    source_has_useful_colors: bool = True,
    color_mode: str = "auto",
    make_views: bool = True,
    view_azimuths: Sequence[float] = (0, 45, 90, 135, 180, 225, 270, 315),
    view_elevations: Sequence[float] = (15, 30),
) -> dict[str, Any]:
    renderer = VTKAnchorRenderer(
        glb_path,
        width=width,
        height=height,
        background_rgb=background_rgb,
        source_has_useful_colors=source_has_useful_colors,
        color_mode=color_mode,
    )
    try:
        view_result = None
        if make_views:
            view_result = renderer.render_view_grid(
                output_dir,
                camera_spec,
                azimuths=view_azimuths,
                elevations=view_elevations,
            )
        aux_result = renderer.render_auxiliary_set(output_dir, camera_spec)
        return {"view_grid": view_result, "aux": aux_result}
    finally:
        renderer.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("glb")
    parser.add_argument("output_dir")
    parser.add_argument("--camera-json")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--azimuth", type=float, default=35)
    parser.add_argument("--elevation", type=float, default=22)
    parser.add_argument("--fov", type=float, default=45)
    parser.add_argument("--framing", type=float, default=0.82)
    parser.add_argument("--projection", choices=["perspective", "orthographic"], default="perspective")
    parser.add_argument("--color-mode", choices=["auto", "original", "pseudo", "clay"], default="auto")
    parser.add_argument("--source-has-colors", action="store_true")
    parser.add_argument("--no-view-grid", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.camera_json:
        camera_spec = json.loads(Path(args.camera_json).read_text(encoding="utf-8"))
    else:
        camera_spec = {
            "azimuth": args.azimuth,
            "elevation": args.elevation,
            "fov_deg": args.fov,
            "framing": args.framing,
            "projection": args.projection,
            "roll": 0,
            "up": [0, 0, 1],
        }
    result = render_auxiliary(
        args.glb,
        args.output_dir,
        camera_spec,
        width=args.width,
        height=args.height,
        source_has_useful_colors=args.source_has_colors,
        color_mode=args.color_mode,
        make_views=not args.no_view_grid,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("VTK_DEFAULT_RENDER_WINDOW_OFFSCREEN", "1")
    raise SystemExit(main())
