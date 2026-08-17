# Optional ComfyUI Geometry Guard

ComfyUI is not required for the main workflow. Use it only after initial candidates show material geometry drift.

## Workflow concept

Build an API-format graph that accepts:

- CAD lineart as an edge/control image.
- CAD depth as a depth/control image.
- CAD color preview as an image-to-image starting point.
- The strict recovery prompt.

Use any locally supported depth/canny-capable model or control adapter. The package does not bundle a checkpoint-specific graph because node IDs and model names vary by installation.

## Required placeholders

Place these literal strings in the exported API workflow:

- `__LINEART_IMAGE__`
- `__DEPTH_IMAGE__`
- `__COLOR_PREVIEW_IMAGE__`
- `__PROMPT__`
- `__OUTPUT_PREFIX__`

`scripts/comfyui_api.py` uploads inputs, replaces placeholders recursively, submits `/prompt`, polls `/history/{prompt_id}`, and downloads outputs through `/view`.

## Test independently

Run the script inside the dedicated environment:

```bash
python scripts/run.py --print-python
# Then use the printed interpreter for the low-level helper when diagnosing a workflow.
```

The guard output is an additional structural reference for the official image-generation retry. It is not automatically accepted as the final beauty image.

## Failure policy

If ComfyUI fails, record a warning and continue the single strict retry using the CAD color preview, clay, lineart, normal, depth, and mask. Do not open an unlimited retry loop.
