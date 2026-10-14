# KYC evidence scoring and evaluation

## Current policy: aggregate PAD routing in the uncalibrated demo (3.4.1)

The combined-score threshold remains **50/100 inclusive**. In the uncalibrated demo only, a measured numeric failure of recording PAD or holding-photo PAD can be routed through that combined score rather than vetoing approval separately. The two derived composites, `document_face_liveness_pad` and `approved_identity_procedure`, may remain false when their only failed inputs are those PAD measurements. Policy version: `demo-routing-v8-pad-score-demo`.

All other controls remain approval gates: OCR and complete server identity, both face comparisons, visible/uncovered faces, document detection, matching NIK, hand proximity, gestures, face continuity, capture quality, bound session proof, applicant authority and absence of security rejection. Missing, duplicate, unavailable or invalid PAD measurements are not eligible. Recording PAD must match the recorded liveness score. Explicit capture, technical and attack states cannot use this exception. Production and approved calibration profiles retain their existing threshold and all-control gates.

The four-component formula is unchanged:

```text
S = (0.25 F + 0.25 P + 0.10 O + 0.30 C) / 0.90
```

Raw PAD probabilities, failed checks, false composites and control-coverage penalties are preserved. The screenshot case therefore stays at **76.98 displayed points** with contributions **26.99 face + 10.77 PAD + 10.90 OCR + 28.33 controls**, while it can now qualify for the synthetic PDF. Decisions use the unrounded score; displayed contributions may not sum exactly after truncation. AI remains an optional diagnostic outside both score and gates. This is an explicit demo process policy, not statistical calibration or evidence that the PAD model became more accurate.

Existing `MANUAL_PENDING` / `MANUAL_SCHEDULED` cases can be rechecked through the owner's revision-bound endpoint `POST /api/applications/{id}/demo/recheck`, carrying only `capture_revision`. The server validates retained sealed evidence, canonical subject, proof binding and authority, then routes the original result. Approval releases the scheduled slot atomically and issues the synthetic PDF. Repeated successful requests are idempotent; another owner, stale revision, expired/misbound evidence and `MANUAL_IN_REVIEW` are refused. Historical cases are not silently bulk-approved.

## Historical policy: optional AI (3.2.1)

The owner's temporary exception makes `Classifier gambar AI (diagnostik)` advisory only. It is excluded by name from the required inventory and workflow composite controls, even if an older result marks it `required`. Its value, reliability, absence, duplicate optional records or inference/load failure cannot change score or core completeness. Required non-AI controls still gate automatic approval. Optional diagnostics remain available for operators without a failed KYC control or manipulation verdict.

AI is removed from the score, not replaced with a fabricated passing value. The other component weights keep their proportions and are normalized:

```text
S = (0.25 F + 0.25 P + 0.10 O + 0.30 C) / 0.90
```

`F/P/O/C` are mapped points for face, PAD, OCR and required-control coverage respectively. The API exposes exact weights/contributions; the UI displays weights to two decimals. An AI-only disagreement therefore cannot produce a failed identity-procedure composite or a technical-pending result. Core health/load and checksum validation do not require the optional AI asset; the optional asset is separately verified before execution and failure is retained as diagnostic metadata. No model, score, PAD/identity/proof gate or historical decision is fabricated.

Feature policy `core-controls-v2-pad-min-geometry-ai-optional` requires a new approved calibration artifact for the four active features and active model hashes; old five-component artifacts are incompatible. Default remains an uncalibrated demo. Existing scheduled cases and their quota/audit/evidence remain intact. Restart, reload and start a new verification to use the new policy.

## Historical policy: all controls including AI (3.2.0)

## Complete evidence and approval

In version 3.2.0, every verification/validation contributed to the evidence inventory and was a gate for automatic approval. A score ≥50/100 was necessary for the uncalibrated demo but could not compensate for a missing, failed or inconclusive control. Operator review and automatic admission to today's quota continued for inconclusive results; technical failures remained retryable. Identity and financial PDF rules were unchanged. The current 3.4.1 exception above supersedes this historical PAD routing rule.

The required inventory covers recorded motion/proof, OCR, capture quality, both visibility checks, both face matches, card detection, matching NIK, hand presence, measured gestures, face continuity, recording PAD, holding-photo PAD, AI image evidence, and Dukcapil. Bound proof, complete server identity, security rejection, applicant authority and identity procedure are also assessed. Missing/duplicate controls and newly added uncertain checks cannot hide through an `advisory` effect. Mock Dukcapil contributes a demo simulation only; it cannot satisfy the official-source requirement in production.

## Formula (default demo, not statistically calibrated)

```text
S = 0.25 × face_points
  + 0.25 × pad_points
  + 0.10 × ocr_points
  + 0.10 × ai_evidence_points
  + 0.30 × control_coverage_points
```

Face/PAD/OCR retain the explicit piecewise-linear demo mapping in `score_policy.py`. Face uses the lower of KTP↔selfie and selfie↔holding cosine. Recording PAD uses the bound temporal median in demo (minimum in strict mode). AI evidence points equal `100 × (1 − max(full-frame AI scores))` only when the two fixed input views are consistent; otherwise this component earns zero evidence points and requires review. Zero usable evidence is **not** a finding that the person/image is fake. Coverage is `100 × passed required controls / total required controls`; each result stores the exact inventory/count, points, weights and contributions.

These weights and points are heuristic design choices, not estimated identity probabilities. Every gate must pass regardless of the weighted total. Missing AI output does not get default zero risk or silently remove its weight. The UI shows an expandable contribution table and blocked controls. Historic results retain their old policy, score and decision.

## PAD defect and input sensitivity

The old final step took `min(recording_median, first_selfie_score)`. The selected selfie was already part of the recording, so one poor first frame could override the new median. For the supplied recording this produced 4.59% despite a median of 72.33%. The new demo uses the trusted recording summary directly when ≥3 bound samples exist; raw selfie scores and the overall minimum remain stored. No old proof is fabricated into a new summary. Strict mode still uses minima.

A local replay on JPEG90 stored evidence found selfie PAD about 68.64%; shifting the detector crop horizontally by −4/+4 pixels produced about 89.35%/96.34%. This establishes sensitivity on this image, not general model accuracy. A geometry-only median of three nearby detector boxes now reduces jitter in streaming PAD. Real movement/scale changes reset the window; any detector miss resets it immediately. Current detection, visibility, recognition and gestures remain mandatory. No previous face replaces a missing face, no crop is chosen for a higher score, and the official +20px/RGB/ImageNet preprocessing remains unchanged. Geometry/raw PAD samples remain in the bound proof.

The face checkpoint was trained with a different detector/data domain; this integration continues to use YuNet. Crop, compression, pose and illumination can expose model sensitivity. CPU and CoreML+CPU outputs matched closely in earlier replay, so those observations did not support an arithmetic/provider-only explanation. Original upload bytes are unavailable after evidence re-encoding; JPEG effects and re-detection cannot be isolated from that replay.

## AI diagnostic defect and abstention

The earlier input reused ArcFace's 112×112 aligned face, then resized it to 224×224 for a generic ViT classifier. Subsequent full-frame classification removed that distortion but also proved large crop dependence. A new local replay scored about 1.33% AI on a full selfie versus 99.76% on a native face region; full holding photo was 0.149% versus 99.822% on its face region. Full-frame low scores alone therefore cannot establish authenticity.

The service now scores two fixed views: full frame and native face region +20px. Both are independently resized with the model's existing processor; no ArcFace alignment or best-score selection. A difference >0.25 is an **experimental disagreement guard**, not a calibrated attack threshold: mark inconclusive, earn no AI evidence points and route to review. Full-frame scores, contextual scores, disagreement and threshold are preserved. A high consistent AI score also requires review, not a fraud verdict. This does not retrain the model or guarantee reliable deepfake detection.

Reference contracts: [CVPR preprocessing](https://github.com/Xianhua-He/cvpr2024-face-anti-spoofing-challenge#data-preprocess), [ViT model card](https://huggingface.co/dima806/deepfake_vs_real_image_detection), and its [processor configuration](https://huggingface.co/dima806/deepfake_vs_real_image_detection/blob/main/preprocessor_config.json).

## Actual calibration and local evaluation

Actual calibration requires labeled genuine/attack captures across cameras, lighting, age groups and attack types, with subject-separated development/evaluation sets. No such dataset has been supplied, so default `calibrated=false` remains accurate. Code changes/regression tests and a replay on one genuine capture cannot prove APCER/BPCER or calibrate a model.

`config/calibration-template.json` now uses schema 2, all five features, model hashes and the exact feature policy (strict minimum PAD, geometry profile, contextual AI). Old three-component artifacts are rejected instead of silently reused. A configured approved artifact still requires its externally approved SHA-256, evaluation report and approver. Empty template fields cannot activate calibration.

Evaluate labeled local result records without upload:

```bash
.venv/bin/python scripts/evaluate_kyc.py labeled-results.jsonl --output evaluation.json
```

Each JSONL record contains `label` (`genuine`/`attack`), `result` (server checks/scores/status), and `mandatory` (server-bound mandatory flags). Both classes are required. Output contains aggregate automatic approval/rejection/manual/technical rates, counts and model/policy identifiers, never raw identity/images. The command does not fit weights, approve calibration, change accounts or mutate stored decisions. Representative sample size and valid labels are the evaluator's responsibility.
