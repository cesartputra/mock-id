# Sumber pihak ketiga

Library runtime dipasang dari PyPI dan mempertahankan lisensi upstream masing-masing. Bobot tidak dimasukkan Git; setup mengambilnya dari URL pada `model-manifest.json`, lalu memverifikasi SHA-256. Periksa ketentuan model/dataset upstream untuk penggunaan di luar demo ini.

## Wrapper yang disertakan

- `app/services/vendor/pipnet/pipnet_onnx.py` dan `meanface.py`: [yakhyo/pipnet-onnx](https://github.com/yakhyo/pipnet-onnx), commit `8ba13d974a67ae1fd9cb0ec12c67ffb9cf6b7fa4`, MIT, copyright 2026 Yakhyokhuja Valikhujaev. Lisensi: `app/services/vendor/pipnet/LICENSE`. Wrapper tidak diubah. Pemanggil memaksa provider CPU. Model berasal dari PIPNet [jhb86253817/PIPNet](https://github.com/jhb86253817/PIPNet).
- `app/services/vendor/mp_palmdet.py`: [opencv/palm_detection_mediapipe](https://huggingface.co/opencv/palm_detection_mediapipe), revision `233e619dcea1759bf6de707b9b904fe30881ea55`.
- `app/services/vendor/mp_handpose.py`: [opencv/handpose_estimation_mediapipe](https://huggingface.co/opencv/handpose_estimation_mediapipe), revision `4b2a0b446e5cf2f11fb6b2c7251091c035d2c1f7`.
- Kedua wrapper OpenCV Zoo menggunakan Apache-2.0, lisensi disertakan di `app/services/vendor/LICENSE-OpenCV-Hand`. Wrapper tidak diubah. Source model MediaPipe: [google-ai-edge/mediapipe](https://github.com/google-ai-edge/mediapipe).

Anti-spoof utama sejak 2.5 memakai checkpoint Swin V2-B area wajah dari [Xianhua-He/cvpr2024-face-anti-spoofing-challenge](https://github.com/Xianhua-He/cvpr2024-face-anti-spoofing-challenge), revision `2b7e9d2f6af93e33806c11ad48f735f1c1810dad`. Source `nets/swin_transformer_v2.py` disertakan untuk ekspor di `app/services/vendor/cvpr2024_swin/model.py`, MIT, copyright 2024 Xianhua He dan header arsitektur copyright 2022 Microsoft. Lisensi repo dan Microsoft disertakan bersama NOTICE perubahan. Crop margin 20 px, RGB 224×224, normalisasi ImageNet; live=0/spoof=1. Checkpoint resmi berasal dari tautan Google Drive di README upstream; SHA dan hasil parity ekspor disertakan di `app/model/swin-pad-export.json`. Runtime hanya memakai ONNX hasil konversi; bobot tidak dimasukkan Git. ViT memakai RGB 224×224, normalisasi mean/std 0.5, label Real=0/Fake=1 sesuai model asal dima806 (Apache-2.0). Sumber/revisi export ONNX ada dalam manifest.

## Fixture test

- `tests/fixtures/astronaut.png`: NASA astronaut Eileen Collins, public domain, distribusi [scikit-image v0.25.2](https://github.com/scikit-image/scikit-image/blob/v0.25.2/skimage/data/astronaut.png). [Dokumentasi sumber](https://scikit-image.org/docs/stable/api/skimage.data.html#skimage.data.astronaut). Dipakai hanya untuk memastikan model benar-benar menjalankan inference, bukan untuk mengevaluasi akurasi biometrik.
- `tests/fixtures/hands.png`: frame ke-10 dari contoh `example_outputs/mphandpose_demo.webp`, distribusi OpenCV Zoo/Hand revision di atas, Apache-2.0. Digunakan untuk smoke test deteksi palm/landmark positif. Atribusi dan lisensi OpenCV sama seperti wrapper.
- Kartu sintetis dibuat lewat OpenCV dalam test dan bertuliskan “KARTU UJI - BUKAN KTP”. Tidak berisi KTP atau data pribadi pemohon.

## FaceAttribNet

`app/services/vendor/face_attribute.py`: wrapper ONNX dari [yakhyo/face-attribute](https://github.com/yakhyo/face-attribute), revision `6b10bc87e4350572eb101f18b624987bc1fdc080`, BSD-3-Clause. Copyright 2025 Qualcomm Technologies, Inc. dan 2026 Yakhyokhuja Valikhujaev. Wrapper disalin tanpa perubahan; lisensi disertakan di `app/services/vendor/LICENSE-FaceAttribute`. Model berasal dari Qualcomm AI Hub. Input letterbox RGB 128×128, nilai 0–1; normalisasi ada di dalam graph, tidak diterapkan dua kali. Lima output adalah probabilitas biner independen, bukan softmax.

`tests/fixtures/face_attributes/*.jpg`: foto uji eyeglasses_man/mask_man/sunglasses_man dari `assets/test_images` pada revision yang sama. Upstream menyatakan foto berasal dari Pexels dengan lisensi bebas. Fixture ini untuk smoke test peringatan model, bukan foto pengguna atau benchmark akurasi umum.

## InsightFace ArcFace ResNet50 (3.1.0)

`arcface_r50.onnx` berasal dari `w600k_r50.onnx` dalam [rilis resmi buffalo_l](https://github.com/deepinsight/insightface/releases/tag/model-zoo), ResNet50@WebFace600K. Manifest mem-pin SHA-256 arsip `80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f` dan anggota `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43`. Setup hanya mengekstrak anggota model, tidak menjalankan kode dari arsip.

[InsightFace](https://github.com/deepinsight/insightface) memakai lisensi MIT untuk kode, tetapi [model zoo](https://github.com/deepinsight/insightface/tree/master/model_zoo) membatasi bobot pretrained ke **riset nonkomersial**. Hak penggunaan bobot produksi/komersial harus diperoleh terpisah. Wrapper `app/services/face.py` diimplementasikan lokal (least-squares similarity transform, normalisasi RGB dan cosine) mengikuti parameter referensi `face_align.py`/`arcface_onnx.py`; tidak menyertakan package atau kode training InsightFace. Tidak ada AdaFace yang diaktifkan.
