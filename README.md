# mock-id — verifikasi identitas lokal

Proyek runnable untuk demo OCR KTP, pencocokan wajah 1:1, tantangan liveness, anti-spoofing, klasifikasi manipulasi gambar, serta KYC dengan foto pemohon memegang KTP. **Pemrosesan foto memakai model open source sungguhan di CPU. Hanya adapter Dukcapil yang mock.**

Backend FastAPI, frontend HTML/CSS/JavaScript, penyimpanan SQLite. Dashboard mulai kosong; tidak ada skenario hasil atau skor preset. Hasil yang belum dikerjakan tampil kosong, dan gangguan model tampil sebagai gangguan teknis.

## Menjalankan pertama kali

Prasyarat: **Python 3.11 atau 3.12**, Node.js 18+, Git, dan internet untuk setup. Gunakan browser modern yang mendukung kamera di localhost. Python 3.14 belum didukung oleh kombinasi wheel inference yang dipakai.

```bash
git clone https://github.com/cesartputra/mock-id.git
cd mock-id
npm run setup
npm start
```

Buka **http://127.0.0.1:4173**. Setup membuat `.venv`, memasang library Python, mengunduh sekitar **206 MiB bobot model**, memverifikasi SHA-256, dan menjalankan smoke test OCR. Dependensi Python memerlukan ruang tambahan. Setup bisa dijalankan ulang; bobot dengan checksum yang sama tidak diunduh lagi. Pemrosesan selanjutnya memakai bobot lokal, tanpa mengirim foto ke layanan model.

Jika Python tidak terdeteksi otomatis:

```bash
MOCK_ID_PYTHON=python3.12 npm run setup
```

Windows PowerShell:

```powershell
$env:MOCK_ID_PYTHON = "C:\Path\To\Python312\python.exe"
npm run setup
npm start
```

Pada macOS, setelah setup Anda juga bisa membuka `Jalankan Demo.command`. Hentikan server dengan Ctrl+C. Jika port dipakai aplikasi lain, gunakan `PORT=4174 npm start` (PowerShell: `$env:PORT="4174"`).

## Mengambil update

Hentikan server yang berjalan, lalu dari folder hasil clone:

```bash
git pull --ff-only
npm run setup
npm start
```

SQLite lokal dan bobot model berada di `.gitignore`; pull tidak menimpa data tersebut. Jika Anda punya perubahan kode lokal, selesaikan commit/stash sebelum pull. Repo berisi kode, manifest download, dan fixture pengujian publik. Bobot besar, foto pemohon, `.venv`, serta database lokal tidak diunggah ke GitHub.

Jika pindah versi Python, buat ulang `.venv` dengan Python 3.11/3.12 sebelum setup. Versi 2 menggantikan frontend simulasi versi 1; data `localStorage` lama tidak diimpor.

## Struktur model, view, controller, services

```text
app/
├── main.py                    # FastAPI, lifecycle, middleware, static files
├── config.py                  # Batas capture, lokasi data, ambang awal
├── model/
│   ├── entities.py            # Model sesi capture
│   ├── repository.py          # Repository SQLite: hasil, audit, konfigurasi
│   └── weights/               # Bobot lokal, diabaikan Git
├── view/
│   └── static/                # index.html, style.css, app.js
├── controller/
│   └── verification.py        # Endpoint, validasi request, respons
└── services/
    ├── pipeline.py            # Orkestrasi pemeriksaan dan keputusan
    ├── ocr.py                 # RapidOCR + parser identitas
    ├── face.py                # YuNet + SFace
    ├── landmarks.py           # PIPNet + MediaPipe Hand ONNX
    ├── antispoof.py           # MiniFASNetV2
    ├── deepfake.py             # ViT Real/Fake
    ├── imaging.py             # Decode, kualitas, perspektif kartu
    ├── sessions.py            # TTL, nonce, retry
    ├── dukcapil.py            # Adapter mock, titik integrasi API resmi
    ├── assets.py              # Pemeriksaan integritas bobot
    └── vendor/                # Wrapper upstream ONNX + lisensi
scripts/                       # Setup dan launcher lintas platform
tests/                         # Unit, API, dan inference nyata
data/                          # SQLite lokal, diabaikan Git
model-manifest.json            # URL/revisi, ukuran dan SHA-256 bobot
requirements.txt               # Versi library runtime yang dipin
```

View mengirim capture ke controller. Controller memvalidasi payload dan sesi, lalu memanggil services. Pipeline menjalankan model dan menyimpan hasil lewat repository. Tidak ada logika keputusan di frontend.

## Alur pemohon

1. Unggah/ambil KTP, setujui pemrosesan lokal, dan jalankan OCR. NIK wajib terbaca sebagai 16 digit; data tidak diisi dengan contoh. Nama, tanggal lahir, dan alamat boleh dikoreksi. NIK tetap mengikuti OCR.
2. Rekam kamera dengan tiga tantangan dalam urutan acak dari server: pejamkan/buka mata, putar kepala, tersenyum. Tiap tantangan mulai dengan empat frame ekspresi netral. Ikuti petunjuk selama sekitar lima detik per tantangan. Tidak ada pilihan mengunggah foto sebagai pengganti rekaman liveness di UI.
3. Ambil/unggah foto wajah sambil memegang KTP. Kartu dan tangan perlu terlihat utuh, teks NIK terbaca, tanpa silau, dan wajah cukup besar.
4. Backend mendeteksi bingkai kartu, melakukan OCR NIK kedua, mencari landmark tangan dekat kartu, mencocokkan wajah KTP↔selfie dan selfie↔KYC, memeriksa perubahan landmark, kontinuitas wajah, PAD, dan risiko manipulasi gambar.
5. Hasil diarahkan ke kontrol lokal terpenuhi, perbaikan capture, gangguan teknis, pemeriksaan manual, atau tinjauan keamanan. Keputusan manual/jadwal dan audit benar-benar tersimpan di SQLite.

Foto memegang KTP memberi **bukti pendukung bahwa orang tersebut terlihat memegang kartu yang sama**. Deteksi tangan dekat kartu merupakan pemeriksaan geometris, sehingga belum membuktikan keaslian fisik KTP atau kepemilikan yang sah secara resmi.

## Library dan model

| Pemeriksaan | Implementasi | Sumber |
|---|---|---|
| OCR | RapidOCR 3.10 / PaddleOCR ONNX, multilingual recognition | [RapidOCR](https://github.com/RapidAI/RapidOCR) |
| Wajah | OpenCV YuNet dan SFace; cosine similarity | [YuNet](https://huggingface.co/opencv/face_detection_yunet), [SFace](https://huggingface.co/opencv/face_recognition_sface) |
| Gerakan | PIPNet 68 landmarks / ONNX Runtime CPU; EAR, lebar mulut, pergeseran hidung | [PIPNet ONNX](https://github.com/yakhyo/pipnet-onnx) |
| Tangan | MediaPipe Palm/Hand versi ONNX melalui OpenCV Zoo | [Palm](https://huggingface.co/opencv/palm_detection_mediapipe), [Hand](https://huggingface.co/opencv/handpose_estimation_mediapipe) |
| Anti-spoof | MiniFASNetV2 / ONNX Runtime CPU | [Face anti-spoofing](https://github.com/yakhyo/face-anti-spoofing), [Silent Face](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing) |
| Manipulasi | ViT dima806 Real/Fake, ONNX quantized | [Model asal](https://huggingface.co/dima806/deepfake_vs_real_image_detection), [Konversi ONNX](https://huggingface.co/onnx-community/deepfake_vs_real_image_detection-ONNX) |
| Dukcapil | Adapter mock yang selalu menyatakan belum diverifikasi | `app/services/dukcapil.py` |

Bobot mengikuti sumber dan checksum dalam manifest. Wrapper PIPNet (MIT) dan OpenCV MediaPipe (Apache-2.0) disertakan dengan lisensinya di `app/services/vendor`; lihat [THIRD_PARTY.md](THIRD_PARTY.md). Runtime tidak memerlukan PyTorch, GPU, native MediaPipe/OpenGL, API key cloud, atau akun Dukcapil.

SFace memakai ambang cosine awal 0.363. Ambang PAD, classifier deepfake, dan blur dapat diubah di UI; seluruh keputusan menggunakan konfigurasi backend. Probabilitas model bukan persentase kepastian identitas. Ambang belum dikalibrasi terhadap kamera, foto KTP, dan populasi pengguna Anda.

Gerakan dihitung dari landmark aktual: baseline eye aspect ratio ≥0.22 lalu tertutup ≤0.19 dan ≤70% baseline; senyum menambah lebar mulut relatif ≥10% dan ≥0.06; putaran kepala mengubah posisi hidung relatif ≥0.12. Batas ini perlu diuji pada perangkat dan kondisi capture Anda.

## Penyimpanan, sesi, dan API

Foto KTP hanya berada dalam memori sesi. Selfie/KYC/frame hanya berada dalam memori request inference; tidak disimpan ke disk. Sesi TTL 15 menit dibersihkan berkala 30 detik, dengan pengecualian request yang masih diproses. Restart menghapus semua sesi. Browser juga menyimpan pratinjau dalam memori selama halaman terbuka.

Database `data/workspace.sqlite3` menyimpan nama, NIK tersamarkan, hasil/skor, audit, jadwal, dan konfigurasi. NIK lengkap maupun gambar tidak disimpan ke SQLite. Ekspor JSON/CSV merupakan unduhan yang dipilih operator. Lokasi database dapat diubah lewat `MOCK_ID_DATA_DIR`.

Nonce server sekali pakai, maksimal tiga percobaan untuk hasil capture/teknis. Backend memeriksa urutan tantangan, minimal delapan frame per tantangan, timestamp, dan banyaknya frame identik. Pemeriksaan ini belum merupakan attestation kamera; klien yang dimodifikasi masih bisa menyusun payload sendiri.

Server launcher mengikat **127.0.0.1**. Host dan Origin dibatasi, dan mutasi API memerlukan `X-Local-Client: mock-id`. Header ini adalah penghalang request lintas situs, **bukan autentikasi operator**. Telemetry FastAPI dinonaktifkan. Untuk demo lokal satu operator; sebelum dipakai multiuser perlu autentikasi, otorisasi, enkripsi data, kebijakan retensi, dan evaluasi keamanan sesuai lingkungan sebenarnya.

Dokumentasi API: **http://127.0.0.1:4173/docs**. Untuk mencoba endpoint mutasi lewat curl/Python atau Swagger, sertakan header `X-Local-Client: mock-id`. Swagger dapat memasukkannya melalui tombol **Authorize**.

```bash
curl -H 'X-Local-Client: mock-id' -X POST http://127.0.0.1:4173/api/sessions
```

Endpoint utama: `/api/health`, `/api/workspace`, `/api/sessions`, `/api/sessions/{id}/document`, `/api/sessions/{id}/identity`, `/api/sessions/{id}/verify`, `/api/sessions/{id}/retry`, `/api/settings`, `/api/records/{id}/review`, `/api/records/{id}/schedule`.

Untuk mengganti Dukcapil mock, implementasikan adapter resmi di `app/services/dukcapil.py` dengan credential dan kontrak API yang disetujui penyedia. Saat ini `identity_verified` selalu **false**, termasuk hasil pass dan persetujuan manual. Aplikasi tidak menyatakan identitas telah diverifikasi oleh Dukcapil.

## Pengujian

```bash
npm run setup:test
npm run check
npm test
```

Tes inference memakai model aktual: OCR NIK dari kartu sintetis, matching pada fixture wajah publik, perubahan skor PAD saat blur, classifier deepfake, penolakan tantangan wajah statis, deteksi tangan positif/negatif, serta deteksi bingkai kartu. Tes API mencakup isolasi data, input tidak valid, nonce, expiry, urutan tantangan, replay, retry, konfigurasi, dan keputusan manual. Tes model di-skip jika bobot belum disiapkan; jalankan setup untuk pengujian lengkap.

Fixture publik hanya untuk pengujian; bukan data pemohon. Uji positif lengkap menggunakan orang di depan kamera dan KTP fisik masih perlu dilakukan di perangkat Anda. Implementasi ini menjalankan pemeriksaan nyata, tetapi belum dinyatakan sebagai sistem KYC produksi atau PAD tersertifikasi. Image classifier deepfake tidak mendeteksi semua video, virtual camera, atau injection.

Aplikasi adalah proyek demo mandiri; bukan layanan resmi OJK/iDebKu/Dukcapil.
