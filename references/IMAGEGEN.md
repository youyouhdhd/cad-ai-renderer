# Official Image-Generation Delegation

## Principle

The local package prepares geometry evidence and a production prompt. Codex's official `$imagegen` Skill performs final image synthesis by default; the host's official image-generation tool is the explicit fallback.

Do not implement a hidden HTTP client in this package. Do not ask the user for an image API key. Do not hardcode a model identifier; allow the official host capability to use its supported image model.

GPT Image 2 is the primary reference target for high-quality product visualization when the host exposes it. It is an integration and evaluation target, not a bundled dependency: this package remains model-neutral and does not call the OpenAI Images API directly.

The default request targets 4K output, high quality, and high visual detail. Built-in host capabilities may not expose exact pixel-size controls; in that case use the highest supported resolution and record the actual dimensions. Never describe an unverified upscale as native 4K.

## Invocation inputs

Read `planning/imagegen_request.json` and `planning/host_handoff.json`. It contains:

- Candidate count.
- Preferred host Skill (`imagegen`).
- Aspect-ratio intent.
- Quality intent.
- Target resolution and detail level.
- Output format.
- Prompt path.
- Ordered input-image paths.
- Role-manifest path.

Preserve the image order. Include each role in the prompt so the generator knows which images are geometry anchors and which are soft appearance references.

## Output strategy

Prefer the official `$imagegen` Skill and a single multi-output invocation per view when supported. Otherwise use four equivalent invocations per view. Keep prompt and input order constant; natural stochastic variation supplies candidate diversity. For a default multi-view run, keep each camera bundle independent and never generate a collage as a substitute for separate views.

Save every returned image locally. Pass the returned file paths directly to the `stage` command template in `host_handoff.json`; do not manually copy them into the run first. Do not treat a contact sheet or a four-panel composition as four candidates.

After staging, use the finalization command from `host_handoff.json` without repeating the generator paths. The finalizer reads the stable copies from `candidates/images/` and only needs the host visual-QA file.

## Tool unavailable

When the host does not expose an official image-generation capability:

1. Finish the local preparation stage.
2. Return the prompt, role manifest, view grid, and auxiliary passes.
3. State that candidate generation was not executed.
4. Do not switch to an undocumented or third-party backend.

## Iteration

Use no more than one strict retry. The retry should be targeted to explicit geometry failures and use `max_geometry` anchors. Keep material/style changes secondary.

## Candidate handoff

Run `stage`, not `finalize`, immediately after generation. Staging imports the files, computes weak local diagnostics, creates the contact sheet and QA prompt, and deliberately leaves the final directory without a selected image. Only run `finalize` after the host has inspected every full-resolution candidate and written visual QA.
