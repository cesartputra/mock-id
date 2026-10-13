# Webcam PAD and image diagnostic correction (3.1.4)

The Swin V2 face checkpoint keeps its existing official face-region preprocessing: detector bounding box plus 20 pixels, RGB 224×224, ImageNet normalization, live class 0. Neither a larger crop chosen for a passing score nor a reversed label is introduced. See the [upstream preprocessing description](https://github.com/Xianhua-He/cvpr2024-face-anti-spoofing-challenge#data-preprocess) and [validation transforms](https://github.com/Xianhua-He/cvpr2024-face-anti-spoofing-challenge/blob/2b7e9d2f6af93e33806c11ad48f735f1c1810dad/datasets/utils.py).

## Corrected input and aggregation

- The generic ViT image diagnostic receives the full decoded camera image, using its original RGB/PIL resize and normalization. It no longer receives the ArcFace 112×112 aligned image. Metadata identifies the input scope and original dimensions. A high diagnostic score is not evidence of manipulation and never determines KYC approval.
- For the uncalibrated local demo, accepted liveness frames are summarized by their median once at least three PAD samples exist. All raw probabilities, their minimum, median, threshold and low-sample count remain in the bound server proof. Fewer than three samples retain the minimum. A new capture starts with an empty sample list.
- Final demo PAD is the lower of the server recording summary and the selfie PAD score. Holding-photo PAD remains real inference, but is a separate advisory diagnostic. It cannot substitute for live gesture evidence or establish card-material authenticity.
- Production and calibrated profiles retain the minimum, including the holding photo and any low historical stream sample. No threshold or model weight changes. The unchanged demo routing threshold is 50/100; the policy version changes to identify these new input semantics.
- Pose/eye/mouth transitions, face continuity, visibility, card/NIK/hand checks, nonce, hash, sequence and evidence bindings still run. A high median alone never completes liveness.

## Local diagnosis and limits

A replay on genuine webcam evidence showed about 0.1% AI-class score on the full frame versus about 99.7% on face crops. Native face crops also scored high, so the problem was not solely 112-to-224 upscaling. The held-photo Swin score was highly sensitive to surrounding crop context; expanding that crop simply to obtain a passing value is not a validated fix. CPU and CoreML+CPU produced nearly identical logits in that replay.

Stored evidence is re-encoded as JPEG quality 90, so replay values can differ from the original capture. These observations diagnose an integration/domain mismatch on one capture, not model accuracy on a representative population. Private faces, KTP data, images and encryption keys are not included in source code, test fixtures or this report. Regression tests use a public image and explicit synthetic protocol fixtures.

The median is a **demo routing statistic**, not a calibrated probability of identity or spoof detection. Full-frame AI diagnostics remain unvalidated for KYC. Webcam genuine/print/screen/replay evaluation and an approved calibration dataset are still required before these outputs can support an operational decision. The change does not guarantee that all false positives disappear.

## Upgrade

Switch to `fix/webcam-pad-scoring`, pull, stop the old server, run `npm start`, and reload the browser at `http://127.0.0.1:4173`. No new weights/dependencies are needed. Start a new liveness capture: historic results are preserved and never fabricated into a new temporal summary.
