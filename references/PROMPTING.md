# Prompting and Missing-Information Policy

## Priority order

1. CAD camera, silhouette, visible topology, proportions, part placement, and occlusion.
2. Explicit user intent and genuine source colors.
3. Reference evidence only within assigned roles.
4. Conservative inference for missing appearance information.

## Why use several CAD images

Do not rely on lineart alone. Lineart communicates silhouette, holes, seams, and hard boundaries but often loses curvature, shallow relief, and occlusion.

Use the default balanced trio:

1. **Color preview**: camera, solid occupancy, part/color blocks, occlusion.
2. **Clay preview**: curvature, bevels, continuous surface form in natural shaded pixels.
3. **Lineart**: crisp silhouette, holes, seams, and visible topology.

Reserve normal, depth, and mask for difficult cases or the one strict retry. Too many technical maps can dilute or confuse appearance instructions.

## Pseudo-color wording

Repeat this concept in the generation prompt:

> Pseudo colors identify CAD parts only. They are not final paint, material, emission, or lighting colors.

## Zero-reference prompt behavior

Use a restrained commercial studio setup. Prefer plausible neutral materials. State assumptions rather than inventing category-specific controls, vents, labels, fasteners, or accessories.

## One mixed reference

Describe reliable and unreliable regions. Example:

```text
Use the reference only for satin aluminum grain, graphite polymer, soft upper-left key light, and warm-gray background. Ignore its object silhouette, handle, vents, feet, camera, labels, and accessories.
```

## Geometry recovery prompt

Name exact failures:

```text
The previous result removed the two circular mounting holes, moved the center seam upward, and widened the base. Restore those three features to the CAD lineart and mask. Keep the selected camera unchanged.
```

Avoid vague language such as “make it closer to the model.”

## Final image requirements

Default to:

- One coherent finished image per candidate.
- Physically plausible material response.
- Controlled highlights that reveal form.
- Credible contact shadow.
- No collage, exploded view, labels, watermark, or unrequested props.
