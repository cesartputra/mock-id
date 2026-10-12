# mock-id — verifikasi identitas lokal

## Versi 3 — permohonan SLIK demo yang persisten

Pembaruan ini ada di branch `development/slik-verification`. Alur lengkap: pemohon tanpa login → verifikasi model nyata → routing → pengambilan otomatis kuota hari ini dan pemeriksaan manual bila perlu → keputusan sah → hasil **DEMO — BUKAN INFORMASI DEBITUR RESMI**. Dukcapil, kewenangan resmi dan penerbitan resmi belum diintegrasikan; produksi ditahan sampai adapter/kalibrasi berwenang tersedia. Tidak ada deployment atau panggilan layanan resmi.

```bash
git fetch origin
git switch development/slik-verification
git pull --ff-only
npm run setup
npm start
```

Hentikan server lama dahulu. Buka `http://127.0.0.1:4173`, langsung pilih **Pendaftaran**. Pemohon tidak membuat akun atau login; cookie HttpOnly mengikat permohonan ke browser yang sama. **Akses petugas** khusus helpdesk/admin yang dibuat melalui terminal; tidak ada credential bawaan:

```bash
npm run user:create -- --login helpdesk-demo --role helpdesk
npm run user:create -- --login administrator-demo --role admin
```

- [Alur, kuota/jadwal, keputusan dan retensi](docs/WORKFLOW.md)
- [Rumus skor demo dan kalibrasi produksi](docs/SCORING.md)
- [Kontrak API dan integrasi widget/backend induk](docs/API.md)
- [Mac M1, CoreML/CPU/CUDA, worker dan deployment adapters](docs/DEPLOYMENT.md)

Sesi kamera sementara dipisahkan dari applications, evidence AES-GCM, cases, jadwal, auth, audit dan issuance di database. Persetujuan manual tetap dapat dilanjutkan setelah restart. Evidence penting yang diganti membatalkan keputusan lama. Backend pendaftaran menolak nama berbeda dari identitas yang diputuskan server. Header `X-Local-Client` kini hanya marker; cookie kapabilitas browser/bearer dan role/resource ownership tetap diwajibkan meskipun pemohon tidak login. Field raw model/diagnostik tersedia untuk operator berwenang; pemohon menerima status, instruksi dan skor routing berlabel heuristik.

QualityGate browser memakai pemeriksaan lokal **heuristik demo** sampai model kualitas yang valid tersedia; interface ONNX Runtime Web/WASM disediakan tanpa model/kemampuan fiktif. Model/server recheck tetap wajib. Tier 2 worker PAD opsional tidak menerima NIK, nonce atau akses DB SLIK. CUDA dependency Linux terpisah dari Mac, dengan fallback runtime sebenarnya. PostgreSQL/private object storage adapters dan Redis owner registry tersedia; capture state masih memerlukan satu gateway/sticky routing, bukan full distributed proof restore.

`npm test` mencakup routing 74,99/75/94/94,99/95/100, mandatory controls, persistence/restart, race slot terakhir, cancel/move/idempotency, holidays/hours, revocation, role/owner authorization, AEAD integrity/retention dan downstream retry. Model CPU asli tetap diuji; fixture routing/manual tidak membuktikan akurasi KYC. Tes fisik NVIDIA/servis deployment dilewatkan bila lingkungan tidak tersedia. Lihat [laporan pengujian](docs/TESTING.md).

Bagian versi 2 di bawah adalah riwayat implementasi. **Endpoint review/schedule legacy kini ditutup**; gunakan applications/manual API. Hasil `pass` kamera sendiri atau status `approved` historis tidak lagi mengotorisasi handoff. Model/reference/licensing tetap sama; struktur MVC ditambah `migrations`, layanan auth/score/workflow/evidence/manual/slik, controller applications/auth dan views workflow/quality-gate.


Proyek lokal dengan halaman pendaftaran bergaya iDebKu dan modul OCR KTP, pencocokan wajah 1:1, tantangan liveness, anti-spoofing, klasifikasi manipulasi gambar, serta KYC dengan foto pemohon memegang KTP. **Pemrosesan foto memakai model open source sungguhan secara lokal; Swin V2 memakai CoreML + CPU otomatis pada Mac Apple Silicon, model lain memakai CPU. Dukcapil dan pendaftaran layanan OJK memakai mock.**

Backend FastAPI, frontend HTML/CSS/JavaScript, penyimpanan SQLite. Dashboard mulai kosong; tidak ada skenario hasil atau skor preset. Hasil yang belum dikerjakan tampil kosong, dan gangguan model tampil sebagai gangguan teknis.

## Menjalankan pertama kali

Prasyarat: **Python 3.11 atau 3.12**, Node.js 18+, Git, dan internet untuk setup. Gunakan browser modern yang mendukung kamera di localhost. Python 3.14 belum didukung oleh kombinasi wheel inference yang dipakai.

```bash
git clone https://github.com/cesartputra/mock-id.git
cd mock-id
npm run setup
npm start
```

Buka **http://127.0.0.1:4173**. Setup membuat `.venv`, memasang library Python, mengunduh sekitar **580 MiB bobot model**, memverifikasi SHA-256, dan menjalankan smoke test OCR. Dependensi Python memerlukan ruang tambahan. Setup bisa dijalankan ulang; bobot dengan checksum yang sama tidak diunduh lagi. Pemrosesan selanjutnya memakai bobot lokal, tanpa mengirim foto ke layanan model.

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

SQLite lokal dan bobot model berada di `.gitignore`; pull tidak menimpa data tersebut. Jika Anda punya perubahan kode lokal, selesaikan commit/stash sebelum pull. Repo berisi kode, manifest download, dan fixture pengujian publik. Bobot tidak dimasukkan ke Git; model Swin V2 tersedia sebagai asset Release pada repo private ini. Foto pemohon, `.venv`, dan database lokal tidak diunggah ke GitHub.

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
    ├── antispoof.py           # Swin V2-B
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
| Anti-spoof | CVPR 2024 Swin V2-B face / ONNX Runtime CoreML + CPU (Apple Silicon) atau CPU | [Implementasi dan checkpoint resmi](https://github.com/Xianhua-He/cvpr2024-face-anti-spoofing-challenge) |
| Diagnostik gambar (tidak menentukan kelulusan) | ViT dima806 Real/Fake, ONNX quantized | [Model asal](https://huggingface.co/dima806/deepfake_vs_real_image_detection), [Konversi ONNX](https://huggingface.co/onnx-community/deepfake_vs_real_image_detection-ONNX) |
| Penutup wajah | FaceAttribNet / ONNX CPU; lima probabilitas independen | [Face Attribute](https://github.com/yakhyo/face-attribute) |
| Dukcapil | Adapter mock yang selalu menyatakan belum diverifikasi | `app/services/dukcapil.py` |

Bobot mengikuti sumber dan checksum dalam manifest. Wrapper PIPNet (MIT), FaceAttribNet (BSD-3-Clause), dan OpenCV MediaPipe (Apache-2.0) disertakan dengan lisensinya di `app/services/vendor`; lihat [THIRD_PARTY.md](THIRD_PARTY.md). Runtime tidak memerlukan PyTorch, GPU, native MediaPipe/OpenGL, API key cloud, atau akun Dukcapil.

SFace memakai ambang cosine awal 0.363. Ambang PAD, cosine, dan blur dapat diubah di UI; keputusan menggunakan konfigurasi backend. Ambang classifier gambar hanya referensi diagnostik dan tidak menentukan kelulusan KYC. Probabilitas model bukan persentase kepastian identitas. Ambang belum dikalibrasi terhadap kamera, foto KTP, dan populasi pengguna Anda.

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

FaceAttribNet mendeteksi kacamata/masker/kacamata hitam secara spesifik. Deteksi wajah terpotong/hilang dan tangan pada wajah memberi peringatan tambahan. Tidak ada jaminan semua jenis benda, rambut, occluder, atau serangan terdeteksi. Swin V2 PAD dan tantangan landmark merupakan pemeriksaan empiris yang perlu dikalibrasi; foto/video/virtual camera tidak dijamin tertolak 100%.

Sesudah pull, hentikan server lama lalu jalankan `npm run setup` untuk mengunduh bobot FaceAttribNet tambahan sekitar 41 MiB. Jalankan `npm start` kembali dan reload halaman; server lama tidak otomatis memuat perubahan endpoint Python.

## Pembaruan 2.3: reset capture dan liveness langsung

Restart server setelah `git pull --ff-only`, kemudian `npm start` dan muat ulang halaman browser. Tidak ada bobot model atau dependensi baru pada pembaruan ini. Pengujian mencakup reset ketiga tahap setelah sesi dikonsumsi, OCR ulang nyata, race OCR/reset, token lama, selfie/proof tampering, urutan/replay frame, transisi kedipan/senyum/putaran, serta penolakan foto publik statis yang digerakkan memakai model ONNX sebenarnya. Uji transisi positif menggunakan metrik landmark sintetis untuk logika temporal; keberhasilan seluruh alur pada webcam fisik dan variasi kamera/pencahayaan masih perlu diuji pengguna.

### Anti-spoof CVPR 2024

Integrasi CPU Swin V2 kini tersedia sejak versi 2.5. Lihat bagian pembaruan 2.5 di bawah untuk checkpoint, kontrak input/output, setup bobot dan batas validasi.

## Pembaruan 2.3: UI pendaftaran iDebKu

Mulai dari beranda, pilih **Pendaftaran → Perseorangan → Lanjut ke verifikasi** untuk OCR/KYC yang sebenarnya. Setelah lolos, lengkapi formulir dan kirim pendaftaran demo. Untuk melihat mock tahap lanjutan tanpa webcam, gunakan **Pratinjau alur setelah KYC**. Semua data dan request demo menuju server lokal. Halaman/brand dibuat sebagai prototipe berdasarkan referensi visual iDebKu; tidak mengubah atau mengirim pendaftaran di situs OJK.

Pengujian API memeriksa penolakan handoff tanpa KYC pass, penolakan setelah capture direset, idempotensi pendaftaran, persistensi nomor demo, label preview, dan jalur non-perseorangan. Pengujian browser mencakup alur formulir → tinjauan → bukti → pencarian status, serta OCR ulang pada ID sesi yang sama dan tombol lanjut yang tetap terkunci sebelum liveness lolos.

### Titik integrasi aplikasi induk

UI publik dipisahkan di `app/view/static/registration.js`; controller/service/model pendaftaran di `app/{controller,services,model}/registration.py`. Ganti adapter pendaftaran mock dengan kontrak aplikasi induk setelah otorisasi integrasi tersedia. Handoff perseorangan menggunakan hasil server `status: pass` dan ID hasil terkini, bukan tanda centang atau flag dari browser. `identity_verified: false` tetap berarti Dukcapil belum memverifikasi identitas. Saat dipindahkan dari loopback ke layanan induk, pembatas Host/Origin, autentikasi, token sesi dan batas retensi perlu disesuaikan dengan arsitektur host; koneksi ke layanan resmi belum dibuat pada demo ini.

## Pembaruan 2.3.1: ulangi hanya tahap yang gagal

Hasil verifikasi memiliki `retry: {stage, label, reason}` dari backend. Tombol utama pada hasil capture failure memanggil `/api/sessions/{id}/retry` dan langsung membuka tahap yang gagal: `document`, `liveness`, atau `holding`. Jika hanya terjadi gangguan teknis (`verify`), ulangi pemrosesan dengan capture yang sama tanpa mengambil foto lagi. Batas percobaan, TTL, nonce sekali pakai, hash selfie/proof, dan penolakan generasi request lama tetap berlaku.

OCR yang diganti tidak menghapus bukti orang hidup yang sudah lolos; bukti ini terikat ke selfie, sedangkan kecocokan wajah KTP↔selfie dan NIK kedua foto KTP tetap dihitung ulang. Foto memegang KTP yang sudah tersedia boleh dipakai kembali setelah liveness baru; final verify memeriksa wajahnya terhadap selfie baru. Capture yang belum lolos liveness tidak dipertahankan sebagai bukti. Jika sesi kedaluwarsa atau server restart, capture lama tidak bisa dipakai lagi.

Label “Kemiripan wajah KTP ↔ selfie” menjelaskan skor cosine (bukan persentase kepastian identitas). Pencocokan wajah dijalankan sebelum OCR kartu dalam foto KYC supaya kegagalan NIK pada foto bersama KTP tidak menyembunyikan skor yang sudah tersedia. Kegagalan kualitas menyebut tahap dan pesan spesifik, misalnya **Kualitas foto bersama KTP — NIK belum terbaca**; “belum terpenuhi” berarti syarat input untuk pemeriksaan tersebut belum lolos, bukan seluruh KYC gagal.

## Pembaruan 2.4: pengambilan kamera otomatis

Tidak ada tombol shutter/foto atau tombol mulai rekam di dialog kamera. Pemohon menyetujui pemrosesan dan mengizinkan kamera, lalu app memeriksa video dengan satu request inferensi aktif:

- **KTP:** dua pemeriksaan lengkap harus membaca NIK yang sama, kualitas gambar memenuhi ambang, dan potret wajah KTP terdeteksi. App memakai frame JPEG resolusi tinggi yang terakhir lolos, menjalankan OCR server, kemudian membuka tinjauan data identitas.
- **Liveness:** setelah tinjauan identitas dilanjutkan, kamera dibuka otomatis. Dua pemeriksaan awal wajah/PAD yang bersih memulai tantangan server tanpa klik rekam. Gerakan dibaca terus-menerus sampai bukti liveness lolos, kemudian app membuka kamera foto bersama KTP otomatis.
- **Foto bersama KTP:** pengambilan menunggu dua pemeriksaan lengkap dengan NIK terbaca/cocok, tangan dekat kartu, wajah cocok dengan KTP, serta visibilitas/PAD terpenuhi. Frame yang sudah diperiksa dipakai langsung; app tidak mengambil snapshot lain setelah respons model. Final verify berjalan otomatis dan tetap menghitung ulang semua kontrol terhadap foto tersebut.

`POST /api/sessions/{id}/auto-capture/check` menerima `context=document|holding` dan `image` maksimum 5 MB. Endpoint tidak menyimpan frame ke disk/audit, tidak mengonsumsi nonce final, dan menolak response yang sudah berbeda generasi sesi. Respons `ready` dari preview wajah saja tidak cukup: gate frontend memerlukan `complete`, NIK terbaca, subject yang konsisten dan (untuk holding) NIK cocok/tangan terdeteksi. Frame tetap memakai limit resolusi backend 1920 px. Laju pengecekan mengikuti CPU/OCR, bukan semua frame video; video browser terus berjalan selama inferensi. Timeout, batas percobaan dan TTL tetap berlaku. Kegagalan fatal sesi menghentikan otomatisasi dengan pesan, sehingga tidak terjadi pengulangan submit tanpa batas. Unggah file tetap tersedia sebagai alternatif.

Tes mencakup auto OCR dan potret memakai model nyata, foto tanpa KTP yang tidak memenuhi gate, prasyarat endpoint, frame/generasi usang, serta gate NIK/tangan/wajah dan trigger sekali untuk dua pemeriksaan konsisten. Tes kontrol holding positif menggunakan stub terpisah untuk logika persyaratan; kemampuan inferensi tiap model diuji dengan fixture publik. Pengambilan lengkap melalui webcam fisik masih perlu diuji pada perangkat pemohon; tidak ada foto pengguna yang digunakan untuk fixture.

## Perbaikan 2.4.1: respons JSON dan pemulihan gangguan server

Hasil deteksi tangan sekarang memakai boolean Python biasa. Sebelumnya, saat tangan ditemukan di dekat kartu, boolean NumPy membuat penyimpanan hasil gagal dan server mengembalikan teks `Internal Server Error`; frontend kemudian menampilkan kesalahan parse JSON. Frontend kini menangani respons teks/HTML/error kosong dengan status HTTP yang jelas. Gangguan API internal dikembalikan sebagai JSON dengan kode error untuk dicocokkan dengan log server, tanpa menampilkan traceback di browser.

Jika pemeriksaan final atau penyimpanan mengalami gangguan, klik **Jalankan model** kembali setelah penyebab gangguan diperbaiki. Klien meminta nonce baru melalui retry terbatas, mempertahankan OCR, selfie/bukti liveness yang sudah lolos, serta foto KYC, lalu memeriksa ulang capture tersebut. Tidak ada pengulangan submit otomatis tanpa batas atau pelonggaran kontrol model. Sesi tetap memiliki batas percobaan dan masa berlaku; restart server menghapus capture dalam memori sehingga memerlukan sesi baru.

Untuk memperbarui: hentikan server dengan `Ctrl+C`, jalankan `git pull --ff-only`, lalu `npm start` dan reload halaman. Perbaikan ini tidak membutuhkan unduhan bobot atau instalasi library tambahan.

## Perbaikan 2.4.2: classifier gambar menjadi diagnostik

Classifier ViT Real/Fake umum belum dikalibrasi untuk potongan wajah hasil kamera KYC. Skor kelas Fake yang tinggi tidak lagi membuat hasil `attack` atau kontrol “Risiko manipulasi gambar — belum terpenuhi”. Hasil pemohon menampilkan skor kecocokan wajah dan PAD serta kontrol KYC utama. Detail operator dan ekspor JSON mempertahankan keluaran classifier asli sebagai `effect: advisory`, `status: informational`, dan `calibrated: false`. Skor tidak diubah menjadi nol atau “asli”; ambang `deepfake_risk` hanya referensi diagnostik. Error saat menjalankan analisis tambahan ini dicatat sebagai diagnostik tidak tersedia tanpa menggagalkan kontrol utama.

Keputusan tetap menahan PAD rendah, tantangan gerakan gagal, visibilitas buruk, kartu/tangan tidak terbaca, ketidaksesuaian NIK/wajah dan kontinuitas wajah. Pendaftaran perseorangan tetap memerlukan hasil server `status: pass`. Hasil baru mencatat `decision_policy: kyc-core-v1-ai-image-diagnostic`; Dukcapil tetap mock. Ini perubahan kebijakan penggunaan model, bukan fine-tuning atau bukti bahwa classifier sudah akurat untuk semua kamera.

Tes regresi kebijakan memakai fixture terpisah: PAD 97,2%, cosine 0,620 dan skor classifier 99,7% tetap dapat lolos ketika kontrol utama terpenuhi; tiap kegagalan kontrol utama tetap menahan handoff. Tes model nyata tetap memakai fixture publik. Webcam/KTP pribadi pengguna tidak dimasukkan ke test fixture. Hasil lama tidak dihitung ulang atau diubah; lakukan pemeriksaan baru sesudah menghentikan server, `git pull --ff-only`, `npm start`, dan reload halaman. Tidak perlu unduhan model atau dependensi baru.

## Pembaruan 2.5: CVPR 2024 Swin V2 sebagai anti-spoof utama

MiniFASNet diganti dengan **Swin V2-B area wajah** dari repo resmi Xianhua-He, revision `2b7e9d2f6af93e33806c11ad48f735f1c1810dad`. Checkpoint `face_swin_v2_base.pth` (SHA-256 `8c0fb53641e42fe0f2a0082ac9b197ffab6d34d9de6eca354d3fa47fe0692ffc`) dikonversi menjadi ONNX FP32/opset 17, berukuran sekitar **335 MiB**. Bobot general-scenario area wajah dipakai; bukan checkpoint full-image atau model protokol kompetisi ResNet. Tidak ada fallback diam-diam ke MiniFASNet.

Preprocessing memakai ROI wajah dengan margin 20 px yang dibatasi bingkai, resize linear 224×224, BGR→RGB dan normalisasi ImageNet mean `[.485,.456,.406]`/std `[.229,.224,.225]`. Tidak dilakukan SFace alignment untuk PAD. Model menghasilkan dua logits: **live=0, spoof=1**, berbeda dari indeks live MiniFASNet sebelumnya. Backend mengembalikan dua probabilitas, label kelas, nama checkpoint, revisi sumber dan runtime ONNX/CPU pada semua pemeriksaan PAD. Swin dipakai di preview, streaming gerakan dan final verify. SFace tetap untuk pencocokan wajah; ViT generic tetap diagnostik seperti versi 2.4.2.

Ekspor dimuat dengan restricted unpickler (`weights_only=True`), state dictionary harus cocok penuh (`strict=True`). Arsitektur upstream disertakan hanya untuk reproduksi ekspor; perubahan terbatas pada helper inference dan konstanta CUDA agar berjalan di CPU. Laporan `app/model/swin-pad-export.json` mencatat parity logits maksimal sekitar **0,000003** pada tiga variasi fixture publik. Benchmark `app/model/swin-pad-benchmark.json` pada Mac arm64, dua thread CPU: median PAD **0,214 detik**, peak proses setelah seluruh model dimuat dan PAD dijalankan **994 MiB**. Angka tersebut bukan waktu total alur kamera atau jaminan penggunaan RAM; frame/capture dan browser menambah kebutuhan memori. Runtime tidak memerlukan PyTorch atau GPU.

### Memperbarui dan mengunduh bobot

Hentikan server dengan `Ctrl+C`, kemudian:

```bash
git pull --ff-only
npm run setup
npm start
```

Reload browser dan mulai sesi baru. Setup mengambil bobot ONNX, memverifikasi SHA-256, lalu warmup. Bobot lama yang sudah valid tidak diunduh ulang. Repo ini private: asset Swin diunduh melalui credential helper GitHub HTTPS yang dipakai untuk clone/pull. Token hanya dikirim ke API GitHub, tidak disimpan atau diteruskan ke CDN. Jika clone memakai SSH dan tidak ada credential HTTPS, unduh `cvpr2024_swin_v2_face.onnx` dari Releases saat login GitHub, taruh di `app/model/weights`, lalu jalankan setup lagi. Aplikasi tidak memakai credential tersebut saat memproses foto.

### Reproduksi ekspor (maintainer)

Runtime aplikasi tidak perlu langkah ini. Siapkan environment terpisah dan pasang `requirements-export-swin.txt`. Unduh checkpoint area wajah dari tautan repo resmi, kemudian:

```bash
python scripts/export_swin_pad.py --checkpoint face_swin_v2_base.pth --checkpoint-sha256 8c0fb53641e42fe0f2a0082ac9b197ffab6d34d9de6eca354d3fa47fe0692ffc --output app/model/weights/cvpr2024_swin_v2_face.onnx --report app/model/swin-pad-export.json
```

Tes memeriksa input RGB/normalisasi, indeks kelas, inference CPU nyata, penolakan foto statis/bergerak oleh rangkaian liveness, integritas model, distribusi credential/redirect dan kontrol KYC yang tetap wajib. Parity ekspor dan fixture publik tidak membuktikan akurasi pada semua webcam. Ambang PAD default 0,80 tetap eksperimen; kalibrasi dengan capture asli dan serangan foto/layar yang representatif masih diperlukan. Tidak ada klaim bahwa Swin pasti menolak semua spoof atau tidak pernah salah pada wajah asli.


## Pembaruan 2.6 — CoreML untuk Mac Apple Silicon

Swin V2 anti-spoof kini memilih `CoreMLExecutionProvider` otomatis ketika Python berjalan sebagai `arm64` di macOS dan provider tersedia. Model ONNX/bobot tetap sama. CoreML memakai **NeuralNetwork**, `MLComputeUnits=ALL`, input statis dan fallback operasi ke CPU. Konfigurasi MLProgram gagal memuat graph Swin pada pengujian lokal, sehingga tidak digunakan. OCR, SFace/YuNet, landmark, tangan, FaceAttrib dan classifier diagnostik tetap memakai CPU; ini adalah pipeline hybrid, bukan pemindahan seluruh aplikasi ke GPU.

ONNX Runtime 1.23.2 yang sudah dipasang menyediakan CoreML EP di Mac ini. Tidak perlu memasang CUDA, PyTorch runtime, atau mengunduh model baru. Python yang berjalan melalui Rosetta/x86_64 akan memakai CPU. CoreML menentukan penempatan operasi pada CPU/GPU/Neural Engine; daftar provider tidak membuktikan perangkat fisik yang dipakai. Lihat [dokumentasi resmi CoreML EP](https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html).

Update dan restart server lama melalui Ctrl+C terlebih dahulu:

```bash
git pull --ff-only
npm start
```

Pilih **Modul & konfigurasi** untuk melihat provider PAD yang dipilih, apakah model sudah dimuat, dan alasan fallback. Sebelum penggunaan pertama status berbunyi “menunggu model dimuat”; model dimuat saat pemeriksaan wajah pertama. Kompilasi CoreML pertama dapat menambah waktu tunggu. Cache tersimpan di `.cache/coreml`, dipisahkan menurut SHA-256 bobot, versi ONNX Runtime dan konfigurasi agar graph lama tidak dipakai setelah update. Jika inisialisasi atau eksekusi CoreML gagal dengan exception, inferensi diulang melalui CPU dan fallback ditampilkan pada health/PAD result. Crash native runtime tidak dapat ditangkap oleh Python; bila proses berhenti, gunakan override CPU berikut.

```bash
# Membandingkan CPU atau mengatasi masalah driver/CoreML:
MOCK_ID_PAD_PROVIDER=cpu npm start
# Default otomatis untuk Apple Silicon:
MOCK_ID_PAD_PROVIDER=auto npm start
# Meminta CoreML; perangkat/provider yang tidak mendukung tetap fallback CPU:
MOCK_ID_PAD_PROVIDER=coreml npm start
```

Konfigurasi berlaku untuk seluruh preview, streaming liveness dan final verify karena ketiganya memakai service PAD yang sama. Tidak ada perubahan ambang, label live/spoof atau aturan kelulusan. Metadata `pad_runtime` pada `/api/health` menunjukkan konfigurasi/provider terdaftar, bukan profil perangkat fisik. Runtime hasil PAD menunjukkan fallback bila terjadi saat inferensi.

```bash
npm run benchmark:coreml
```

Benchmark memeriksa checksum model, menjalankan CPU dan CoreML pada tiga variasi fixture astronaut publik, membandingkan logits/probabilitas, dan membaca event profiler untuk membuktikan operasi CoreML benar-benar dieksekusi. Laporan disimpan di `.cache/coreml-benchmark/report.json`. Pada Mac arm64/ORT 1.23.2 di lingkungan pengujian ini: median tujuh inferensi hangat CPU **0,2278 detik**, CoreML hybrid **0,2326 detik**, initialization masing-masing **0,633 / 4,527 detik**. CoreML mengeksekusi operasi, tetapi **belum lebih cepat** pada pengujian ini; sandbox macOS juga mengeluarkan peringatan akses cache. Jalankan benchmark di terminal biasa pada Mac Anda untuk menilai latensi aktual. Jumlah event provider tidak boleh dibaca sebagai persentase FLOPs atau waktu GPU. Laporan tersimpan di `app/model/swin-pad-coreml-benchmark.json`; selisih logits maksimum **0,0000043**, probabilitas **0,00000000083**. Ini validasi integrasi pada fixture publik, bukan akurasi KYC, RAM total atau FPS video kamera.

Tes regresi KYC memakai CPU sebagai baseline yang konsisten; tes kebijakan provider memeriksa pemilihan Apple Silicon, override CPU, invalidasi cache, fallback saat compile/run/registrasi dan pelaporan status. Benchmark CoreML nyata dijalankan terpisah untuk menghindari kompetisi resource dengan tes.
