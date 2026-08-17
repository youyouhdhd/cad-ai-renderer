# Attachment Discovery and Reference Roles

## Discovery rules

Treat the current message attachments as the primary input source. Do not ask users to duplicate paths into a project file.

Model preference order:

1. STEP/STP.
2. GLB.
3. GLTF.
4. OBJ.
5. STL.
6. PLY.
7. 3MF.

Treat every supported raster image as a candidate reference unless the user identifies it as an output or unrelated file.

When several 3D files exist, use explicit user wording first. If one STEP and one derived mesh share a stem, prefer STEP. Ask only when equally plausible source models remain.

## Reference role inference

Use any combination of:

- `camera`: viewpoint, lens feel, elevation, rotation.
- `composition`: crop, object placement, negative space.
- `material`: substrate and surface finish.
- `color`: palette or region-level color assignment.
- `lighting`: direction, softness, contrast, reflections.
- `style`: photographic or illustrative treatment.
- `environment`: studio/background/context.
- `detail`: small appearance cues that are not topology.
- `mixed`: insufficiently separable evidence.

A colored CAD screenshot often has roles `[camera, composition, color, mixed]`. A product photograph often has `[material, color, lighting, style, environment]`. A mood image may have only `[lighting, style, environment]`.

## Allowed and forbidden use

For every reference, explicitly state both.

Example:

```json
{
  "reference_index": 0,
  "image_index": 1,
  "roles": ["material", "color", "lighting"],
  "allowed_use": "Use brushed aluminum grain, graphite polymer color, and soft upper-left studio light.",
  "forbidden_use": "Do not copy the photographed object's handle, vents, buttons, silhouette, proportions, or part count.",
  "notes": "Camera is too different to use.",
  "confidence": 0.88
}
```

## No-reference behavior

Do not block. Infer a conservative premium render and write assumptions. Avoid category-specific features that do not exist in CAD.

## One-reference behavior

Split the evidence. A single image can simultaneously be useful for material and lighting but harmful for geometry. Never grant it blanket authority.

## Missing color behavior

When source CAD colors are absent:

- Use pseudo-color preview as a part segmentation aid.
- Use clay preview as the natural shaded form cue.
- Do not use pseudo colors as final paint without explicit support.
- Infer a restrained palette from user text, product category, or reference evidence.
