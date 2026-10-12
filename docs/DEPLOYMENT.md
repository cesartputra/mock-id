# Profil runtime dan deployment (tidak melakukan deployment)

## Mac M1 lokal

```bash
git fetch origin
git switch development/slik-verification
git pull --ff-only
npm run setup
npm start
```

Python 3.11/3.12 native arm64, Node >=18. Setup memasang dependency baru cryptography dan memverifikasi bobot existing; ArcFace R50 menggantikan recognizer SFace, sementara Swin tetap dipakai. Default auto: CoreML NeuralNetwork + CPU pada Apple Silicon, CPU pada perangkat lain, CUDA + CPU pada Linux dengan CUDA EP. Model lain/PIPNet, OCR, ArcFace R50, tangan, penutup dan diagnostik tetap CPU. `MOCK_ID_PAD_PROVIDER=cpu|coreml|cuda|auto` mengubah profil PAD, bukan keputusan. CoreML bisa sama lambat atau lebih lambat dari CPU; jangan mengasumsikan GPU/ANE dipakai semua operasi. `npm run benchmark:coreml` memeriksa parity dan profiler nyata.

Salin .env.example ke .env bila diperlukan. Launcher membaca plain key/value, tidak mengeksekusi shell. CLI user:create meminta sandi interaktif. Hentikan server lama sebelum restart agar frontend baru tidak berpasangan dengan backend lama. Data/key lokal tidak masuk Git.

## Tier dan antrean

Client QualityGate: heuristik lokal default. Interface ONNX Runtime Web dengan WASM/CPU menerima model/artifact nyata dari host, bukan model fiktif; runtime tidak diunduh otomatis dari CDN. [ONNX Runtime Web resmi](https://onnxruntime.ai/docs/get-started/with-javascript/web.html).

Tier 1 gateway CPU: OCR, completeness, dokumen/subjek, wajah dan identity adapter. Koordinator liveness/landmark tetap CPU di gateway. Tier 2 PAD: local CPU/CoreML/CUDA atau worker HTTP terpisah. `InferenceQueue` memberi satu worker pemilik mutable model, maksimal empat pekerjaan diterima dan response timeout 30 detik (worker PAD 20). Model lock existing tidak dihapus. Timeout **tidak** membatalkan native inference; slot/session tetap terkunci sampai pekerjaan sungguh selesai. Preview tidak mengonsumsi nonce. Ketika admission penuh, 429/backpressure; model error tidak dijadikan skor nol.

## Worker PAD Linux NVIDIA

Gunakan venv **terpisah**, bukan memasang CPU dan GPU ORT di env yang sama:

```bash
python3.12 -m venv .venv-gpu
.venv-gpu/bin/python -m pip install -r requirements-gpu.txt
```

Profil memakai `onnxruntime-gpu==1.23.2`, membutuhkan driver NVIDIA, CUDA/cuDNN yang cocok; periksa [matriks CUDA EP resmi](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html). Jangan memasang CUDA pada Mac. Bobot Swin yang SHA-pinned sama harus tersedia di app/model/weights; worker memeriksa SHA sebelum load. Gunakan credential model-download di proses provisioning saja, tidak di worker runtime.

Set `MOCK_ID_WORKER_TOKEN` dari secret manager (minimal 32 karakter, jangan credential dalam Git/argument CLI), kemudian:

```bash
MOCK_ID_PAD_PROVIDER=cuda .venv-gpu/bin/python -m uvicorn app.worker:app --host 127.0.0.1 --port 4181 --no-access-log
```

Gateway mempunyai `MOCK_ID_PAD_WORKER_URL` dan token yang sama. HTTP loopback hanya di demo; remote/deployment HTTPS diwajibkan. Deploy worker di jaringan privat melalui TLS/mTLS gateway yang dipercaya dan allowlist hanya gateway aplikasi. `/v1/pad` menerima float32 NCHW [1,3,224,224], panjang tetap, nilai finite. Tensor diproses langsung; identitas, nonce, proof, aplikasi, kapasitas, keputusan dan DB SLIK tidak ada di worker. Worker mengembalikan checksum model, kelas live=0/spoof=1, raw probabilities dan provider/fallback aktual. Gateway menolak checksum/contract berbeda dan credential-bearing redirect. Worker unavailable menahan pemeriksaan teknis, bukan skor fabricated atau klaim CPU sukses. Koordinator gerakan/proof tetap di backend, tidak menerima keputusan dari worker.

`npm run worker` memakai .venv lokal untuk pengujian CPU/CoreML. Dashboard runtime berlabel menunggu respons worker sebelum inference pertama. CUDA gagal init/run → CPU fallback yang benar-benar dihitung ulang dan dilaporkan. Pengujian fisik GPU harus dijalankan di mesin NVIDIA; pada Mac tes itu dilewatkan, tidak disebut berhasil.

## SQLite / PostgreSQL / storage

SQLite adalah profil lokal. Migrasi di app/model/migrations, dijalankan transaksi dan versioned saat startup. Hasil historis tetap disimpan; approval legacy tidak otomatis memberi kewenangan. Unique IDs/foreign keys menjaga cases/issuance. Writes serial pada SQLite `BEGIN IMMEDIATE`; PostgreSQL memakai advisory xact lock untuk admission/kapasitas/state updates, bukan lock proses Python saja. Versi awal menserialisasi writes antar instance; ukur contention sebelum workload besar.

Dependency deployment opsional `requirements-deployment.txt`: psycopg, boto3, Redis. `MOCK_ID_DATABASE_URL` memilih PostgreSQL; gunakan database/schema khusus, TLS (`sslmode=verify-full` pada jaringan eksternal), least-privilege credential dari secret manager dan migrasi sebelum menerima traffic. Semua instance wajib memakai encryption key yang sama dari secret manager. Private object storage melalui S3 adapter memiliki public access block; AES-GCM aplikasi tetap berlaku di atas server-side encryption. [AEAD cryptography](https://cryptography.io/en/latest/hazmat/primitives/aead/), [transaksi psycopg](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).

Capture streaming masih merupakan state mutable satu gateway: **jangan** load-balance frame sesi yang sama ke gateway berbeda. Aplikasi, keputusan, evidence, jadwal, auth, rate limits dan issuance dapat dibagi melalui PostgreSQL; jalankan satu capture gateway atau sticky routing ke gateway owner. Redis registry opsional memetakan session→gateway owner dengan TTL; tidak menserialisasi/menghidupkan kembali proof liveness dari memori setelah restart. Recovery kamera tetap capture baru. Ini batas implementasi yang eksplisit; shared full capture state/attestation kamera bukan fitur yang diklaim tersedia. Worker PAD dapat dibagi karena stateless input tensor; keputusan/bukti tidak bergantung pada memori worker.

Issuance lease 60 detik dapat direklaim setelah crash dengan ID sama. Respons attempt lama ditolak oleh lease token. Recovery IN_FLIGHT otomatis hanya pada startup SQLite satu instance; PostgreSQL memakai expiry lease. Adapter downstream resmi perlu deadline <lease atau renewal/lease yang sesuai, idempotensi dan receipt audit. Proxy TLS harus mengirim forwarded headers hanya dari proxy terpercaya. Set MOCK_ID_ALLOWED_HOSTS secara eksplisit; tidak ada wildcard/CORS permisif.

## Produksi tetap ditahan

`MOCK_ID_MODE=production` menuntut encryption key aman, HTTPS dan identitas/kewenangan/kanal penerimaan dari prosedur host yang disetujui. Browser publik boleh masuk tanpa login; cookie kapabilitas tidak memenuhi validasi identitas resmi. Signup/receipt mock browser dinonaktifkan. Tanpa artefak kalibrasi disetujui, AUTO_APPROVED tidak diizinkan. Tanpa validation identity dan requester authority adapter berwenang, persetujuan/penerbitan ditahan. Adapter SLIK resmi default belum dikonfigurasi; ia tidak memanggil layanan resmi. Kanal dashboard dengan kepemilikan browser adalah default demo; email bukan kanal terverifikasi di sini.

Belum ada deployment, koneksi resmi OJK/Dukcapil, audit keamanan/SOP produksi, IdP/SSO pihak OJK, key rotation otomatis, distributed full camera state, atau pembuktian akurasi/populasi/ketahanan semua serangan. Jangan menyebut demo ini siap operasi SLIK resmi. CPU/CoreML native diuji lokal; CUDA, PostgreSQL server dan object storage nyata memerlukan pengujian environment deployment.

## Model wajah 3.1.0

`npm run setup` mengunduh arsip resmi InsightFace buffalo_l (275 MiB), memverifikasi SHA-256 arsip, lalu mengekstrak **hanya** `w600k_r50.onnx` sebagai `arcface_r50.onnx` (166 MiB). Checksum anggota juga diverifikasi. Bobot diabaikan Git, tidak di-commit. Model ONNX ini berjalan pada CPU; CoreML tetap mempercepat PAD sesuai konfigurasi yang sudah ada. Tidak ada dependency InsightFace Python/training baru. Alignment 5 landmark 112×112, RGB normalisasi `(pixel-127.5)/127.5`, embedding 512 dimensi. Model zoo melisensikan bobot untuk riset nonkomersial saja; penggunaan produksi memerlukan hak bobot yang sesuai. RAM/storage bertambah dibanding recognizer SFace lama.
