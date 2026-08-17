# Executed Validation Report

This package was validated through `scripts/run.py`, using the same managed-environment entrypoint that the skill instructs Codex to use.

## Portable bootstrap and recovery

The launcher was exercised in four migration-relevant states:

1. **Cold start without package-index access.** The isolated pip attempt failed quickly, then the launcher created a separate `host-linked` virtual environment from compatible packages already present in the selected runtime. It did not modify the global interpreter.
2. **Warm reuse.** A second `--no-install bootstrap` invocation reused the ready environment without running pip.
3. **Interrupted host-linked creation.** Metadata and install-state files were removed while the host-package `.pth` link was retained. The next bootstrap detected the interrupted state, verified imports, restored atomic metadata, and reported `mode: host-linked` instead of misclassifying the environment as isolated.
4. **Dead or migrated bootstrap lock.** A same-host lock owned by a nonexistent process was removed automatically. A fresh lock whose owner hostname differed from the current machine was also treated as a copied migration artifact instead of blocking startup.

The launcher also passed deterministic unit checks for compatible-interpreter discovery, explicit interpreter override, partial-install resume selection, and subcommand-specific help dispatch.

## Real STEP self-test

Status: **passed — 18 of 18 checks**.

1. `required_dependencies`
2. `dedicated_environment_contract`
3. `portable_bootstrap_selection_and_resume`
4. `command_specific_help_dispatch`
5. `generate_real_step_and_reference_fixtures`
6. `attachment_input_discovery_without_yaml`
7. `two_stage_camera_grid`
8. `direct_input_step_to_auxiliary_pipeline`
9. `windows_safe_portable_output_layout`
10. `auxiliary_images_nonblank`
11. `official_image_skill_delegation_contract`
12. `local_geometry_metric_ranking`
13. `candidate_staging_does_not_prematurely_select`
14. `candidate_visual_qa_and_finalization`
15. `idempotent_structured_final_report`
16. `colorless_step_detection`
17. `model_neutral_configuration_validation`
18. `no_model_lock_or_raw_image_api_client`

The test generated a colored STEP assembly and a colorless mechanical bracket, discovered a model plus reference image directly from attachment-style paths, converted STEP to GLB, produced a 16-view camera grid, and rendered color preview, clay, lineart, mask, normal, depth, and part-ID passes.

All auxiliary images were nonblank. The colorless STEP was correctly reported with `source_has_useful_colors: false`.

The canonical output directory is `auxiliary/`. No run creates a directory named `aux`, which is a reserved Windows device name. Legacy `aux/` output can still be read on platforms where such a directory already exists.

Four deliberately degraded synthetic candidates produced the following local diagnostic order:

| Candidate | Local geometry score |
|---|---:|
| C01 | 80.372 |
| C02 | 56.653 |
| C03 | 26.035 |
| C04 | 14.752 |

These metrics are intentionally non-authoritative. The staging test verified that local diagnostics create a contact sheet and return `awaiting_visual_qa` without writing `final/best.png` or `final/selection.json`.

A separate host-style visual-QA file was then supplied. Finalization reused the stable candidate copies created during staging, selected C01, wrote the best image, and rebuilt the report. Re-running finalization produced an identical report with exactly one Candidate QA section.

## Direct CLI regression

The public command sequence was also executed outside the in-process self-test:

```text
stage --run ... --candidate C01=... --candidate C02=... --candidate C03=... --candidate C04=...
finalize --run ... --visual-qa visual_qa.json
```

The stage command returned `awaiting_visual_qa` and created no final image. The finalize command accepted no repeated candidate paths, rediscovered the staged copies, returned `complete`, and selected C01.

## Scope boundary

The local validation covers environment initialization, interruption recovery, attachment discovery, STEP conversion, deterministic auxiliary rendering, image-generation handoff manifests, candidate staging, local diagnostics, host-QA ingestion, final selection, and report generation.

The host-only official image-generation skill/tool cannot be invoked from the standalone Python test. Actual image synthesis therefore remains a host capability. The supplied rollout already exercised that host boundary successfully; this package validates the deterministic preparation and handoff contract around it.

A VTK warning about the unavailable X display appeared in the headless validation container. Offscreen rendering nevertheless completed and every required PNG passed nonblank verification.
