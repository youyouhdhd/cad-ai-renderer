# Executed Validation Report

This package was validated through `scripts/run.py`, using the same managed-environment entrypoint that the skill instructs Codex to use.

## Portable bootstrap and recovery

The launcher was exercised in four migration-relevant states:

1. **Cold start without package-index access.** The isolated pip attempt failed quickly, then the launcher created a separate `host-linked` virtual environment from compatible packages already present in the selected runtime. It did not modify the global interpreter.
2. **Warm reuse.** A second `--no-install bootstrap` invocation reused the ready environment without running pip.
3. **Interrupted host-linked creation.** Metadata and install-state files were removed while the host-package `.pth` link was retained. The next bootstrap detected the interrupted state, verified imports, restored atomic metadata, and reported `mode: host-linked` instead of misclassifying the environment as isolated.
4. **Dead, migrated, or concurrently-created bootstrap lock.** Dead and foreign-host locks were removed. A fresh ownerless directory was preserved during the mkdir-to-owner-file grace interval, preventing parallel launchers from deleting a valid lock underneath its creator.

The launcher also passed deterministic unit checks for compatible-interpreter discovery, explicit interpreter override, partial-install resume selection, and subcommand-specific help dispatch.

## Real STEP self-test

Status: **passed — 23 of 23 checks**.

1. `required_dependencies`
2. `dedicated_environment_contract`
3. `portable_bootstrap_selection_and_resume`
4. `command_specific_help_dispatch`
5. `generate_real_step_and_reference_fixtures`
6. `attachment_input_discovery_without_yaml`
7. `editable_render_plan_confirmation_gate_and_candidate_policy`
8. `two_stage_camera_grid`
9. `default_directional_multi_view_bundle`
10. `contract_frozen_stage_aware_anchor_pipeline`
11. `windows_safe_portable_output_layout`
12. `auxiliary_images_nonblank`
13. `official_image_skill_delegation_contract`
14. `retry_delta_preserves_frozen_contract_and_revises_once`
15. `local_geometry_metric_ranking`
16. `candidate_staging_does_not_prematurely_select`
17. `candidate_visual_qa_selects_without_premature_delivery`
18. `idempotent_structured_final_report`
19. `final_refinement_resolution_gate_and_exact_delivery`
20. `frozen_contract_tamper_rejected_and_restore_verified`
21. `colorless_step_detection`
22. `model_neutral_configuration_validation`
23. `no_model_lock_or_raw_image_api_client`

The test generated a colored STEP assembly and a colorless mechanical bracket, discovered attachment-style inputs, created and gated a render plan, converted STEP to GLB, produced fourteen named reference views plus four final-generation view bundles, rendered all passes at separate grid/candidate/final-anchor resolutions, and validated every frozen contract hash.

The adaptive-resolution probe resolved an automatic square 4K final-anchor contract to `4096x4096`; explicit lightweight self-test overrides remained `384x384` for candidate anchors and `512x512` for final anchors.

All auxiliary images were nonblank. The colorless STEP was correctly reported with `source_has_useful_colors: false`.

The canonical output directory is `auxiliary/`. No run creates a directory named `aux`, which is a reserved Windows device name. Legacy `aux/` output can still be read on platforms where such a directory already exists.

Four deliberately degraded synthetic candidates produced the following local diagnostic order:

| Candidate | Local geometry score |
|---|---:|
| C01 | 80.070 |
| C02 | 56.470 |
| C03 | 24.570 |
| C04 | 14.820 |

These metrics are intentionally non-authoritative. The staging test verified that local diagnostics create a contact sheet and return `awaiting_visual_qa` without writing `final/best.png` or `final/selection.json`.

A host-style visual-QA file selected R01 without creating a final image. The pipeline then wrote a frozen final-refinement request, staged one synthetic F01 master, required final QC, delivered exact 768×768 pixels from a 384×384 source, and correctly reported `complete_exact_dimensions_upscaled`, `upscaled: true`, and `target_met_natively: false`. Re-running selection and finish remained idempotent.

The retry test kept the same contract ID, incremented its revision once, changed only the exact failure list and `max_geometry` anchor mode, and rejected a retry payload that attempted to modify the camera. A separate tamper test changed a frozen component file, verified that every downstream command rejected it, restored the file, and revalidated the contract.

## Complex real-model smoke test

The repository pipeline was also run against `sc_solid_stp_20260429.stp` (about 8.6 MB) with one confirmed front view. It produced render-plan schema 1.1 and a revision-1 frozen contract with one C01 candidate, `requested_native_size: auto`, exact `1280x720` delivery, a `256x256` candidate anchor, a `512x512` final anchor, and `tool_parameters.candidate_count: 1`. CAD conversion and all contract files completed successfully.

## Direct CLI regression

The public command sequence was also executed outside the in-process self-test:

```text
stage --run ... --candidate R01=... --candidate R02=... --candidate R03=... --candidate R04=...
finalize --run ... --visual-qa visual_qa.json
refine-stage --run ... --master F01=...
finish --run ... --final-qa final_qc.json
```

The stage command returned `awaiting_visual_qa` and created no selection or final image. Candidate finalization returned `awaiting_final_refinement`. Only `finish` created `final/best.png`, together with `resolution_report.json` and `final_qc.json`.

## Scope boundary

The local validation covers environment initialization, concurrent-lock safety, attachment discovery, STEP conversion, stage-aware auxiliary rendering, frozen contracts, tool-parameter handoff, retry deltas, candidate native-size reports, candidate QA/selection, final refinement handoff, final QC, exact-pixel delivery, resolution state reporting, and idempotent reports.

The host-only official image-generation skill/tool cannot be invoked from the standalone Python test. Actual image synthesis therefore remains a host capability. The supplied rollout already exercised that host boundary successfully; this package validates the deterministic preparation and handoff contract around it.

A VTK warning about the unavailable X display appeared in the headless validation container. Offscreen rendering nevertheless completed and every required PNG passed nonblank verification.
