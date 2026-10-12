# mock-id — verifikasi identitas lokal

Proyek lokal dengan halaman pendaftaran bergaya iDebKu dan modul OCR KTP, pencocokan wajah 1:1, tantangan liveness, anti-spoofing, klasifikasi manipulasi gambar, serta KYC dengan foto pemohon memegang KTP. **Pemrosesan foto memakai model open source sungguhan di CPU. Dukcapil dan pendaftaran layanan OJK memakai mock.**

Backend FastAPI, frontend HTML/CSS/JavaScript, penyimpanan SQLite. Dashboard mulai kosong; tidak ada skenario hasil atau skor preset. Hasil yang belum dikerjakan tampil kosong, dan gangguan model tampil sebagai gangguan teknis.

## Menjalankan pertama kali

Prasyarat: **Python 3.11 atau 3.12**, Node.js 18+, Git, dan internet untuk setup. Gunakan browser modern yang mendukung kamera di localhost. Python 3.14 belum didukung oleh kombinasi wheel inference yang dipakai.

```bash
git clone https://github.com/cesartputra/mock-id.git
cd mock-id
npm run setup
npm start
```

Buka **http://127.0.0.1:4173**. Setup membuat `.venv`, memasang library Python, mengunduh sekitar **247 MiB bobot model**, memverifikasi SHA-256, dan menjalankan smoke test OCR. Dependensi Python memerlukan ruang tambahan. Setup bisa dijalankan ulang; bobot dengan checksum yang sama tidak diunduh lagi. Pemrosesan selanjutnya memakai bobot lokal, tanpa mengirim foto ke layanan model.

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
│   ├── verification.py        # Endpoint, validasi request, respons
│   └── registration.py        # Endpoint handoff pendaftaran demo
└── services/
    ├── pipeline.py            # Orkestrasi pemeriksaan dan keputusan
    ├── ocr.py                 # RapidOCR + parser identitas
    ├── face.py                # YuNet + SFace
    ├── landmarks.py           # PIPNet + MediaPipe Hand ONNX
    ├── antispoof.py           # MiniFASNetV2
    ├── deepfake.py             # ViT Real/Fake
    ├── card.py                # Kartu: geometri, fitur referensi, susunan teks
    ├── visibility.py          # FaceAttribNet dan umpan balik kamera
    ├── imaging.py             # Decode, kualitas, perspektif kartu
    ├── sessions.py            # TTL, nonce, reset per tahap
    ├── liveness.py            # State machine gerakan streaming
    ├── registration.py        # Adapter pendaftaran demo lokal
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

Halaman awal mengikuti pola [iDebKu OJK](https://idebku.ojk.go.id/Public/HomePage): aksen merah, Pendaftaran, dan Status Layanan. Pendaftaran menawarkan **Perseorangan**, **Badan usaha**, dan **Debitur meninggal dunia**. Modul OCR/KYC/liveness dijalankan pada jalur perseorangan WNI/KTP; dua jenis lain menampilkan mock formulir dan checklist dokumen tanpa pemeriksaan wajah. Ini belum menggantikan seluruh aturan/dokumen layanan resmi.

Setelah hasil KYC lokal berstatus `pass`, tombol **Lanjut ke pendaftaran** membuka data kontak/tujuan permohonan, tinjauan, konfirmasi, dan bukti bernomor `DEMO-…`. Adapter menyimpan pendaftaran ke SQLite lokal; tidak memanggil API OJK, mengirim email, atau menerbitkan laporan SLIK. Status demo dapat dicari kembali lewat nomor pendaftaran. Tombol **Pratinjau alur setelah KYC** di beranda menyediakan contoh formulir tanpa menjalankan kamera; semua halaman/bukti diberi label pratinjau, tidak membuat hasil KYC, dan `identity_verified` tetap false.

Workspace operator tetap ada pada `/#dashboard`, termasuk konfigurasi dan antrean hasil inference. Halaman publik default ada pada `/` atau `/#home`. Untuk jalur perseorangan:

1. Unggah/ambil KTP, setujui pemrosesan lokal, dan jalankan OCR. NIK wajib terbaca sebagai 16 digit; data tidak diisi dengan contoh. Nama, tanggal lahir, dan alamat boleh dikoreksi. NIK tetap mengikuti OCR.
2. Buka kamera untuk liveness. Video tetap berjalan dan frame dikirim berurutan ke backend dengan satu request aktif. Model mendeteksi wajah, memeriksa PAD/penutup wajah, dan mengukur landmark mata, mulut, serta kepala. Tiga tantangan dan arah putaran diacak server. Tiap tantangan dimulai dari tiga sampel netral; kedipan harus melalui mata terbuka → tertutup → terbuka, senyum/putaran harus terbaca dua sampel berturut-turut. Tantangan langsung berganti ketika bukti gerakan terpenuhi, tanpa durasi tetap lima detik. Kotak wajah dan kemajuan ditampilkan saat respons model tiba. Kecepatan inferensi bergantung CPU, bukan setiap frame video ditayangkan. Tombol lanjut hanya aktif setelah bukti server lolos. Tidak ada unggahan foto sebagai pengganti liveness di UI.
3. Pratinjau kamera memeriksa kacamata, masker, kacamata hitam, tangan di wajah, kualitas capture, serta risiko foto/layar sekitar sekali per detik sebelum pemeriksaan dimulai. Saat liveness berjalan, pemeriksaan ini mengikuti setiap frame inferensi. Penutup wajah atau blur menghentikan akumulasi gerakan dan memerlukan posisi netral lagi; dua sinyal spoof berurutan mengakhiri pemeriksaan. Tombol capture foto menunggu dua pemeriksaan bersih. Ambil/unggah foto wajah sambil memegang KTP. Kartu dan tangan perlu terlihat utuh, teks NIK terbaca, tanpa silau, dan wajah cukup besar.
4. Backend mendeteksi bingkai kartu, melakukan OCR NIK kedua, mencari landmark tangan dekat kartu, mencocokkan wajah KTP↔selfie dan selfie↔KYC, memeriksa perubahan landmark, kontinuitas wajah, PAD, dan risiko manipulasi gambar.
5. Hasil diarahkan ke kontrol lokal terpenuhi, perbaikan capture, gangguan teknis, pemeriksaan manual, atau tinjauan keamanan. Keputusan manual/jadwal dan audit benar-benar tersimpan di SQLite. Pilihan ambil ulang OCR, liveness, atau Foto + KTP membersihkan data tahap tersebut dalam ID sesi yang sama. OCR ulang mengganti foto/hasil OCR, mempertahankan bukti liveness yang sudah lolos dan foto KYC yang tersedia; liveness ulang mengganti selfie/bukti gerakan dan mempertahankan OCR serta foto KYC; foto KYC ulang mempertahankan OCR serta bukti liveness. Seluruh pencocokan wajah dan NIK diperiksa lagi terhadap capture terbaru, sehingga foto lama tidak otomatis dianggap sesuai dengan dokumen baru. Nonce dan generasi capture diperbarui; respons lama ditolak. Riwayat hasil yang sudah disimpan tetap ada.

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
| Penutup wajah | FaceAttribNet / ONNX CPU; lima probabilitas independen | [Face Attribute](https://github.com/yakhyo/face-attribute) |
| Dukcapil | Adapter mock yang selalu menyatakan belum diverifikasi | `app/services/dukcapil.py` |

Bobot mengikuti sumber dan checksum dalam manifest. Wrapper PIPNet (MIT), FaceAttribNet (BSD-3-Clause), dan OpenCV MediaPipe (Apache-2.0) disertakan dengan lisensinya di `app/services/vendor`; lihat [THIRD_PARTY.md](THIRD_PARTY.md). Runtime tidak memerlukan PyTorch, GPU, native MediaPipe/OpenGL, API key cloud, atau akun Dukcapil.

SFace memakai ambang cosine awal 0.363. Ambang PAD, classifier deepfake, dan blur dapat diubah di UI; seluruh keputusan menggunakan konfigurasi backend. Probabilitas model bukan persentase kepastian identitas. Ambang belum dikalibrasi terhadap kamera, foto KTP, dan populasi pengguna Anda.

Gerakan dihitung dari landmark aktual: baseline eye aspect ratio ≥0.22 lalu tertutup ≤0.19 dan ≤70% baseline; senyum menambah lebar mulut relatif ≥10% dan ≥0.06; putaran kepala mengubah posisi hidung relatif ≥0.12. Batas ini perlu diuji pada perangkat dan kondisi capture Anda.

## Penyimpanan, sesi, dan API

Foto KTP hanya berada dalam memori sesi. Frame inferensi dan foto KYC tidak disimpan ke disk. Satu frame selfie referensi ditahan dalam memori selama streaming untuk kontinuitas wajah, lalu dilepas ketika streaming selesai atau direset; server menyimpan hash selfie dan bukti gerakan sampai sesi berakhir. Sesi TTL 15 menit dibersihkan berkala 30 detik, dengan pengecualian request yang masih diproses. Restart menghapus semua sesi. Browser juga menyimpan pratinjau dalam memori selama halaman terbuka.

Database `data/workspace.sqlite3` menyimpan nama, NIK tersamarkan, hasil/skor, audit, jadwal, dan konfigurasi. Tabel `registrations` juga menyimpan nama, email, ponsel, alamat dan tujuan dari formulir pendaftaran demo; gunakan data contoh untuk pengujian mock UI. Data pendaftaran bertahan setelah restart untuk pencarian status. NIK lengkap maupun gambar tidak disimpan ke SQLite. Ekspor JSON/CSV merupakan unduhan yang dipilih operator. Lokasi database dapat diubah lewat `MOCK_ID_DATA_DIR`.

Nonce final verify sekali pakai, maksimal tiga percobaan verifikasi dalam satu sesi. Pengambilan ulang setelah final verify menghitung percobaan berikutnya; penggantian capture sebelum final verify tidak menambah hitungan ini. Streaming liveness memiliki token dan maksimum tiga pemeriksaan tersendiri per percobaan verifikasi. Reset biasa tidak menghapus pembatas ini. Server memeriksa urutan frame, frame identik, kontinuitas wajah, PAD, serta transisi gerakan; bukti streaming diterbitkan server dan terikat hash selfie. Final verify menolak selfie/bukti yang diganti atau nonce yang sudah digunakan. Header `X-Capture-Revision` mengikat request klien ke generasi capture; hasil OCR/preview lama yang selesai sesudah reset ditolak. Reset ditolak sementara inferensi liveness/final verify sedang berjalan, agar hasil tidak bercampur.

Streaming memiliki batas 90 detik/360 frame dan minimal selang 90 ms per request sebagai pembatas resource, **bukan durasi kelulusan gerakan**. Jeda lebih dari tiga detik membatalkan baseline gerakan yang sedang berlangsung. Endpoint batch lama (`/liveness/check`) tetap didukung untuk kompatibilitas dan memiliki aturan 24–48 frame/manifest sebelumnya; UI versi 2.3 memakai `/liveness/frame`. Pemeriksaan ini belum merupakan attestation kamera; klien yang dimodifikasi masih bisa menyusun input sendiri.

Server launcher mengikat **127.0.0.1**. Host dan Origin dibatasi, dan mutasi API memerlukan `X-Local-Client: mock-id`. Header ini adalah penghalang request lintas situs, **bukan autentikasi operator**. Telemetry FastAPI dinonaktifkan. Untuk demo lokal satu operator; sebelum dipakai multiuser perlu autentikasi, otorisasi, enkripsi data, kebijakan retensi, dan evaluasi keamanan sesuai lingkungan sebenarnya.

Dokumentasi API: **http://127.0.0.1:4173/docs**. Untuk mencoba endpoint mutasi lewat curl/Python atau Swagger, sertakan header `X-Local-Client: mock-id`. Swagger dapat memasukkannya melalui tombol **Authorize**.

```bash
curl -H 'X-Local-Client: mock-id' -X POST http://127.0.0.1:4173/api/sessions
```

Endpoint kamera/liveness: `/api/sessions/{id}/capture-check`, `/api/sessions/{id}/liveness/start`, `/api/sessions/{id}/liveness/frame`. Preview dibatasi dua request per detik; streaming memakai backpressure satu request aktif dan tidak menyimpan gambar ke audit/disk. `liveness/start` mengembalikan token dan tantangan; `liveness/frame` menerima `capture_nonce`, `seq` mulai 0, dan `image`. Respons mengandung kotak wajah, peringatan, metrik gerakan, tantangan saat ini, serta bukti jika semua gerakan lolos. UI mempertahankan blob frame yang ditunjuk `selfie_seq`; final verify mengirim blob itu, `proof_token`, `nonce`, dan foto `holding`.

`POST /api/sessions/{id}/retake` menerima JSON `{"stage":"document|liveness|holding","nonce":"nonce sesi terbaru"}` dan mengembalikan nonce/revision baru. Klien versi 2.3 mengirim header `X-Capture-Revision` untuk semua request capture. ID sesi, TTL, dan riwayat audit tetap dipertahankan.

Endpoint pendaftaran mock: `POST /api/registrations` dan `GET /api/registrations/{id}`. Jalur perseorangan normal memerlukan `session_id` dan `verification_id` dari hasil pass terakhir pada sesi yang belum direset. Submit berulang pada hasil yang sama mengembalikan bukti yang sudah dibuat. `preview: true` menghasilkan bukti pratinjau terpisah dan tidak pernah memberikan status KYC lolos. Jalur badan usaha/meninggal dunia tidak menerima bukti KYC.

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

## Pembaruan capture KYC dan liveness

Kartu tidak harus membentuk empat tepi sempurna: pencarian memakai kandidat geometri/warna, homografi SIFT terhadap foto KTP awal, dan OCR seluruh foto untuk mencari blok NIK beserta label KTP di sekitarnya. Setiap kandidat tetap harus menghasilkan pembacaan NIK baru. NIK dari foto pertama tidak pernah dipakai untuk mengisi hasil OCR kedua. Spasi/hyphen dalam satu baris NIK dapat dinormalisasi; huruf tidak ditebak menjadi angka. Foto kecil/buram tetap bisa salah terbaca atau memerlukan capture ulang.

Resolusi foto kamera ditargetkan 1920×1080 (bergantung perangkat), JPEG kualitas 0.95, dan backend mempertahankan sisi panjang sampai 1920 px. Frame preview/liveness tetap 640 px untuk membatasi beban. Panduan kartu menggunakan rasio 1.586 agar kartu lebih besar dan proporsional.

FaceAttribNet mendeteksi kacamata/masker/kacamata hitam secara spesifik. Deteksi wajah terpotong/hilang dan tangan pada wajah memberi peringatan tambahan. Tidak ada jaminan semua jenis benda, rambut, occluder, atau serangan terdeteksi. MiniFASNetV2 dan tantangan landmark merupakan pemeriksaan empiris yang perlu dikalibrasi; foto/video/virtual camera tidak dijamin tertolak 100%.

Sesudah pull, hentikan server lama lalu jalankan `npm run setup` untuk mengunduh bobot FaceAttribNet tambahan sekitar 41 MiB. Jalankan `npm start` kembali dan reload halaman; server lama tidak otomatis memuat perubahan endpoint Python.

## Pembaruan 2.3: reset capture dan liveness langsung

Restart server setelah `git pull --ff-only`, kemudian `npm start` dan muat ulang halaman browser. Tidak ada bobot model atau dependensi baru pada pembaruan ini. Pengujian mencakup reset ketiga tahap setelah sesi dikonsumsi, OCR ulang nyata, race OCR/reset, token lama, selfie/proof tampering, urutan/replay frame, transisi kedipan/senyum/putaran, serta penolakan foto publik statis yang digerakkan memakai model ONNX sebenarnya. Uji transisi positif menggunakan metrik landmark sintetis untuk logika temporal; keberhasilan seluruh alur pada webcam fisik dan variasi kamera/pencahayaan masih perlu diuji pengguna.

### Kandidat anti-spoof CVPR 2024

Repo [Xianhua-He/cvpr2024-face-anti-spoofing-challenge](https://github.com/Xianhua-He/cvpr2024-face-anti-spoofing-challenge) menyediakan kode penelitian, checkpoint general-scenario, dan [ekspor MobileNet ke ONNX](https://github.com/Xianhua-He/cvpr2024-face-anti-spoofing-challenge/blob/main/export/export_mobilenet.sh). Model bisa ditambahkan sebagai backend PAD atau dibandingkan sebelum mengganti MiniFASNet. Input full-image/face-area dan indeks kelasnya berbeda; README menyatakan live=0, spoof=1. Skrip pengujian PyTorch aslinya menggunakan CUDA/distributed, sehingga bukan dependensi yang cukup dipasang langsung ke app CPU ini. Integrasi membutuhkan adapter preprocessing/output, checksum bobot, validasi hasil ekspor ONNX, pengukuran latency/RAM, dan kalibrasi threshold dengan data wajah asli/foto/layar yang representatif. Versi 2.3 tetap memakai MiniFASNet; model CVPR tersebut belum diintegrasikan atau diuji di aplikasi ini.

## Pembaruan 2.3: UI pendaftaran iDebKu

Mulai dari beranda, pilih **Pendaftaran → Perseorangan → Lanjut ke verifikasi** untuk OCR/KYC yang sebenarnya. Setelah lolos, lengkapi formulir dan kirim pendaftaran demo. Untuk melihat mock tahap lanjutan tanpa webcam, gunakan **Pratinjau alur setelah KYC**. Semua data dan request demo menuju server lokal. Halaman/brand dibuat sebagai prototipe berdasarkan referensi visual iDebKu; tidak mengubah atau mengirim pendaftaran di situs OJK.

Pengujian API memeriksa penolakan handoff tanpa KYC pass, penolakan setelah capture direset, idempotensi pendaftaran, persistensi nomor demo, label preview, dan jalur non-perseorangan. Pengujian browser mencakup alur formulir → tinjauan → bukti → pencarian status, serta OCR ulang pada ID sesi yang sama dan tombol lanjut yang tetap terkunci sebelum liveness lolos.

### Titik integrasi aplikasi induk

UI publik dipisahkan di `app/view/static/registration.js`; controller/service/model pendaftaran di `app/{controller,services,model}/registration.py`. Ganti adapter pendaftaran mock dengan kontrak aplikasi induk setelah otorisasi integrasi tersedia. Handoff perseorangan menggunakan hasil server `status: pass` dan ID hasil terkini, bukan tanda centang atau flag dari browser. `identity_verified: false` tetap berarti Dukcapil belum memverifikasi identitas. Saat dipindahkan dari loopback ke layanan induk, pembatas Host/Origin, autentikasi, token sesi dan batas retensi perlu disesuaikan dengan arsitektur host; koneksi ke layanan resmi belum dibuat pada demo ini.

## Pembaruan 2.3.1: ulangi hanya tahap yang gagal

Hasil verifikasi memiliki `retry: {stage, label, reason}` dari backend. Tombol utama pada hasil capture failure memanggil `/api/sessions/{id}/retry` dan langsung membuka tahap yang gagal: `document`, `liveness`, atau `holding`. Jika hanya terjadi gangguan teknis (`verify`), ulangi pemrosesan dengan capture yang sama tanpa mengambil foto lagi. Batas percobaan, TTL, nonce sekali pakai, hash selfie/proof, dan penolakan generasi request lama tetap berlaku.

OCR yang diganti tidak menghapus bukti orang hidup yang sudah lolos; bukti ini terikat ke selfie, sedangkan kecocokan wajah KTP↔selfie dan NIK kedua foto KTP tetap dihitung ulang. Foto memegang KTP yang sudah tersedia boleh dipakai kembali setelah liveness baru; final verify memeriksa wajahnya terhadap selfie baru. Capture yang belum lolos liveness tidak dipertahankan sebagai bukti. Jika sesi kedaluwarsa atau server restart, capture lama tidak bisa dipakai lagi.

Label “Kemiripan wajah KTP ↔ selfie” menjelaskan skor cosine (bukan persentase kepastian identitas). Pencocokan wajah dijalankan sebelum OCR kartu dalam foto KYC supaya kegagalan NIK pada foto bersama KTP tidak menyembunyikan skor yang sudah tersedia. Kegagalan kualitas menyebut tahap dan pesan spesifik, misalnya **Kualitas foto bersama KTP — NIK belum terbaca**; “belum terpenuhi” berarti syarat input untuk pemeriksaan tersebut belum lolos, bukan seluruh KYC gagal.
