# Optional Project YAML Schema

A project YAML is optional and intended for reproducible batch or advanced use. Normal conversation use discovers attachments directly.

## `project`

- `name`: Run name.
- `input_model`: STEP/STP or supported mesh path.
- `output_dir`: Output directory.
- `description`: Natural-language user intent.
- `references`: Optional list of paths or objects. Bare paths default to role `mixed`; the host should infer roles.

## `camera`

- `mode`: `auto`, `reference`, or `manual`.
- `projection`: `perspective` or `orthographic`.
- `azimuth`, `elevation`, `roll`: Degrees.
- `fov_deg`: 1-150; host plans should normally remain 24-75.
- `framing`: 0.2-0.98; host plans should normally remain 0.65-0.90.
- `position`, `target`, `up`: Optional exact camera vectors.
- `view_grid_azimuths`, `view_grid_elevations`: Deterministic camera grid.

## `geometry`

- `converter`: `auto`, `cadquery`, `freecad`, or `passthrough`.
- `linear_tolerance`, `angular_tolerance`: STEP tessellation controls.
- `color_mode`: `auto`, `original`, `pseudo`, or `clay`.
- `anchor_mode`: `compact`, `balanced`, or `max_geometry`.
- `up_axis`: Currently `z`.
- `repair`: Reserved for future repair stages.

## `render`

- `aux_backend`: `auto` or `vtk`.
- `width`, `height`: Backward-compatible aliases for candidate anchors.
- `view_grid_resolution.width`, `.height`: Camera-selection renderer input, 256-4096.
- `candidate_anchor_resolution.width`, `.height`: Candidate-generation anchors, 256-4096.
- `final_anchor_resolution.width`, `.height`: Final-refinement anchors, 256-4096; both null selects an aspect-preserving 2048-4096 adaptive size from the final output contract.
- `background_rgb`: Three values from 0 to 1.
- `transparent_aux`: Reserved; default false.

## `generation`

These become frozen host-tool parameters after preparation:

- `candidates`: 1-10; default 4.
- `aspect_ratio`: `auto`, `1:1`, `4:3`, `3:4`, `16:9`, or `9:16`.
- `quality`: `auto`, `draft`, `standard`, or `high`.
- `target_resolution`: `auto`, `2k`, or `4k`; used to derive final dimensions when none are explicit.
- `requested_native_size`: `auto` or exact `WIDTHxHEIGHT`. Exact values must be passed as a tool size argument when supported.
- `detail_level`: `standard` or `high`.
- `output_format`: `png`, `jpeg`, or `webp`.
- `max_retries`: 0 or 1.

## `final_output`

- `width`, `height`: Optional exact output dimensions, 256-8192. Supply both or neither.
- `format`: `png`, `jpeg`, or `webp`.
- `resize_policy`: `fit_pad`; preserves the whole image and pads rather than cropping.
- `allow_upscale`: Allow exact-dimension non-native delivery. Upscaling remains explicitly reported.

## `qa`

- `min_geometry_score`: Geometry gate from 0 to 100.
- `min_visual_quality_score`: Final visual-quality gate from 0 to 100.
- `local_weight`, `visual_weight`: Must sum to 1.
- `max_edge_distance_px`: Local edge tolerance.
- `retry_on_geometry_drift`: Allow a single targeted retry.

## `comfyui`

- `enabled`: Enable only as an optional geometry guard.
- `server_url`: Local ComfyUI server.
- `workflow`: API-format workflow JSON.
- `timeout_seconds`: At least 30.
