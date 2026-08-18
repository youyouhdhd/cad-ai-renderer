# Official Image-Generation Delegation

## Principle

The local package prepares geometry evidence and a production prompt. Codex's official `$imagegen` Skill performs final image synthesis by default; the host's official image-generation tool is the explicit fallback.

Do not implement a hidden HTTP client in this package. Do not ask the user for an image API key. Do not hardcode a model identifier; allow the official host capability to use its supported image model.

GPT Image 2 is the primary reference target for high-quality product visualization when the host exposes it. It is an integration and evaluation target, not a bundled dependency: this package remains model-neutral and does not call the OpenAI Images API directly.

The frozen output contract separates requested native generation size from exact final delivery pixels. Built-in host capabilities may not expose exact size controls; use the highest supported size matching the frozen aspect ratio, record actual pixels, and let the later resolution gate perform any allowed exact-dimension resampling. Never describe an upscale as native 4K.

## Invocation inputs

Read `planning/render_contract.json`, `planning/imagegen_request.json`, and `planning/host_handoff.json`. They contain:

- Candidate count.
- Preferred host Skill (`imagegen`).
- Frozen contract ID and revision.
- Actual `tool_parameters` for supported host fields.
- Aspect ratio and requested native-size policy.
- Quality intent.
- Exact final output width and height, separate from native generation.
- Output format.
- Prompt path.
- Ordered input-image paths.
- Role-manifest path.

Preserve the image order. Pass supported machine fields as tool arguments; only scene/material/geometry semantics belong in the prompt. Never rewrite a contract field from the conversation.

## Output strategy

Prefer the official `$imagegen` Skill and follow the confirmed `generation_plan.views` exactly. The
default reference plan may contain fourteen deterministic views, but those references do not multiply
the final-image budget:

- without a specified output view, generate exactly four final candidates total—front, back, left,
  and one upper axonometric;
- with a specified output view, generate four candidates in that view by default;
- with a specified view and quantity, use the requested quantity in that view;
- if the user edits the plan, use its view entries and candidate IDs as the source of truth.

Use one multi-output invocation per view when supported. Otherwise make the exact number of equivalent
invocations listed for that view. Keep prompt and input order constant; natural stochastic variation
supplies candidate diversity. Keep each camera bundle independent and never generate a collage as a
substitute for separate views.

Save every returned image locally. Pass the returned file paths directly to the `stage` command template in `host_handoff.json`; do not manually copy them into the run first. Do not treat a contact sheet or a four-panel composition as four candidates.

After staging, run candidate finalization without repeating transient paths. It selects a source and writes `final_refine_request.json`; it does not deliver a final image.

Invoke exactly one final-refinement generation using the selected candidate plus high-resolution CAD anchors. Keep camera, crop, composition, geometry, scene, aspect ratio, and final dimensions frozen. Stage F01, perform final QC, then run `finish`. The resolution report records requested/actual native size, requested/delivered final size, megapixels, resampling, upscaling, native-target pass, refinement use, and final-anchor size.

## Tool unavailable

When the host does not expose an official image-generation capability:

1. Finish the local preparation stage.
2. Return the prompt, role manifest, view grid, and auxiliary passes.
3. State that candidate generation was not executed.
4. Do not switch to an undocumented or third-party backend.

## Iteration

Use no more than one strict retry. It must be a validated `retry_delta.json` against the current contract revision, list exact geometry failures, and use `max_geometry` anchors. Frozen fields cannot change.

## Candidate handoff

Run `stage`, not `finalize`, immediately after candidate generation. Staging imports files, records native pixels, computes weak local diagnostics, creates the contact sheet and QA prompt, and deliberately leaves the final directory without a selection. Run `finalize` only after full-resolution host QA. Then generate one final master, run `refine-stage`, write final QC, and run `finish`; only `finish` creates `final/best.*`.
