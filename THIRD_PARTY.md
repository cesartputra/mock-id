# Sumber pihak ketiga

Library runtime dipasang dari PyPI dan mempertahankan lisensi upstream masing-masing. Bobot tidak dimasukkan Git; setup mengambilnya dari URL pada `model-manifest.json`, lalu memverifikasi SHA-256. Periksa ketentuan model/dataset upstream untuk penggunaan di luar demo ini.

## Wrapper yang disertakan

- `app/services/vendor/pipnet/pipnet_onnx.py` dan `meanface.py`: [yakhyo/pipnet-onnx](https://github.com/yakhyo/pipnet-onnx), commit `8ba13d974a67ae1fd9cb0ec12c67ffb9cf6b7fa4`, MIT, copyright 2026 Yakhyokhuja Valikhujaev. Lisensi: `app/services/vendor/pipnet/LICENSE`. Wrapper tidak diubah. Pemanggil memaksa provider CPU. Model berasal dari PIPNet [jhb86253817/PIPNet](https://github.com/jhb86253817/PIPNet).
- `app/services/vendor/mp_palmdet.py`: [opencv/palm_detection_mediapipe](https://huggingface.co/opencv/palm_detection_mediapipe), revision `233e619dcea1759bf6de707b9b904fe30881ea55`.
- `app/services/vendor/mp_handpose.py`: [opencv/handpose_estimation_mediapipe](https://huggingface.co/opencv/handpose_estimation_mediapipe), revision `4b2a0b446e5cf2f11fb6b2c7251091c035d2c1f7`.
- Kedua wrapper OpenCV Zoo menggunakan Apache-2.0, lisensi disertakan di `app/services/vendor/LICENSE-OpenCV-Hand`. Wrapper tidak diubah. Source model MediaPipe: [google-ai-edge/mediapipe](https://github.com/google-ai-edge/mediapipe).

Preprocessing MiniFASNet mengacu pada [yakhyo/face-anti-spoofing](https://github.com/yakhyo/face-anti-spoofing) dan [Silent-Face-Anti-Spoofing](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing) (Apache-2.0). Implementasi service memakai crop BGR 80×80, scale 2.7, dan kelas live pada indeks 1. ViT memakai RGB 224×224, normalisasi mean/std 0.5, label Real=0/Fake=1 sesuai model asal dima806 (Apache-2.0). Sumber/revisi export ONNX ada dalam manifest.

## Fixture test

- `tests/fixtures/astronaut.png`: NASA astronaut Eileen Collins, public domain, distribusi [scikit-image v0.25.2](https://github.com/scikit-image/scikit-image/blob/v0.25.2/skimage/data/astronaut.png). [Dokumentasi sumber](https://scikit-image.org/docs/stable/api/skimage.data.html#skimage.data.astronaut). Dipakai hanya untuk memastikan model benar-benar menjalankan inference, bukan untuk mengevaluasi akurasi biometrik.
- `tests/fixtures/hands.png`: frame ke-10 dari contoh `example_outputs/mphandpose_demo.webp`, distribusi OpenCV Zoo/Hand revision di atas, Apache-2.0. Digunakan untuk smoke test deteksi palm/landmark positif. Atribusi dan lisensi OpenCV sama seperti wrapper.
- Kartu sintetis dibuat lewat OpenCV dalam test dan bertuliskan “KARTU UJI - BUKAN KTP”. Tidak berisi KTP atau data pribadi pemohon.
