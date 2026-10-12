# Demo verifikasi dan permohonan persisten

Profil ini **bukan layanan resmi OJK**, tidak memanggil Dukcapil/SLIK resmi dan tidak mengirim email. Status AUTO_APPROVED/MANUAL_APPROVED pada demo mengizinkan **hasil sintetis saja**. Identitas resmi tetap `identity_verified=false`. Laporan dengan data keuangan sintetis berlabel **DEMO — BUKAN INFORMASI DEBITUR RESMI**. Nama, NIK, tanggal lahir dan alamat debitur berasal dari bukti identitas server yang diputuskan. Kreditur, plafon, baki debet, suku bunga dan riwayat kredit adalah contoh acak sintetis, bukan kondisi keuangan orang tersebut.

## Alur dan batas kepercayaan

```mermaid
flowchart TD
  A[Pemohon tanpa login / cookie browser / permohonan persisten] --> B[Camera + QualityGate lokal]
  B --> C[Tier 1 CPU: OCR, identitas, wajah 1:1]
  C --> D[Tier 2: liveness PIPNet + Swin PAD]
  D --> E[Server: proof, nonce, revision, metrik asli]
  E --> F[ScorePolicy + pemeriksaan wajib]
  F -->|>=95 dan seluruh syarat / profil diizinkan| G[AUTO_APPROVED]
  F -->|>=75 dan <95 atau syarat butuh tinjauan| H[MANUAL_PENDING]
  F -->|<75 / aturan keamanan| I[REJECTED: permohonan ini]
  F -->|capture / model belum tersedia| J[CAPTURE_RETRY / TECHNICAL_PENDING]
  J --> B
  H --> K[Kuota hari ini otomatis: transaksi kapasitas dan retensi]
  K --> L[MANUAL_SCHEDULED]
  L --> M[MANUAL_IN_REVIEW: petugas terikat kasus]
  M --> N[MANUAL_APPROVED / MANUAL_REJECTED / perbaikan]
  G --> O[Backend induk: otorisasi keputusan, subjek, kanal]
  N -->|persetujuan sah| O
  O --> P[SLIK_PENDING: issuance ID + lease]
  P --> Q[SLIK_READY: laporan sintetis demo]
```

State machine diperiksa backend, bukan oleh field browser. Kamera berumur 15 menit, dengan maksimal tiga sesi kamera per permohonan, tiga final attempts per sesi, tiga pengambilan OCR, tiga retake dokumen/foto/hasil final per tahap. Mulai ulang liveness sebelum proof/final verification tidak dibatasi tiga rekaman; timeout 90 detik/360 frame per stream, TTL sesi, rate limit, antrean dan proof binding tetap berlaku. Dua detector miss dalam satu detik menahan evidence tanpa mereset baseline; miss lebih lama atau penutup wajah mereset action. Frame yang hilang tidak menghasilkan evidence/hits/proof. Rate limit login, signup, capture, write dan session start disimpan di DB. Angka adalah contoh demo, bukan SOP OJK. Sesi expired membutuhkan capture baru; **keputusan manual, kasus, bukti, jadwal dan hasil tetap tersedia setelah restart**.

## Pemohon

1. `npm run setup`, `npm start`, buka localhost:4173.
2. Langsung pilih Pendaftaran → Perseorangan, tanpa login. Browser memperoleh kapabilitas acak 256-bit melalui cookie HttpOnly/SameSite Strict. Permohonan/hasil hanya tersedia pada browser yang memegang cookie tersebut. Login tetap diperlukan petugas.
3. Setujui pemrosesan dan pernyataan permohonan untuk diri sendiri. OCR, selfie/gerakan dan foto memegang KTP memakai model sebenarnya. Nama/tanggal lahir harus lengkap; NIK berasal dari OCR. KTP tidak dikirim ke pihak luar pada profil lokal.
4. QualityGate browser memberi panduan blur, cahaya dan silau dengan **heuristik demo**, serta posisi dari kotak wajah terakhir yang diberikan server. Ia tidak memiliki model visibilitas wajah baru. Server tetap memeriksa wajah/penutup, NIK, wajah 1:1, PAD dan proof. Bila model kualitas yang sesuai tersedia, `QualityGate.loadOnnx` mendukung runtime ONNX Runtime Web yang disediakan aplikasi induk, WASM default, bytes model dengan SHA-256, kontrak RGB NCHW [1,3,N,N] 0–1 dan output probabilitas kualitas tunggal. Tidak ada model kualitas fiktif atau unduhan browser/CDN otomatis.
5. Hasil MANUAL_PENDING otomatis mengambil satu kuota **hari ini** dalam transaksi atomik. Sebelum jam buka, slot hari ini dapat dipesan untuk pemeriksaan saat layanan buka. Setelah jam tutup, hari libur atau kuota penuh, tetap MANUAL_PENDING dengan pesan dan hari kerja berikutnya sebagai petunjuk (bukan janji/reservasi). Klik Cek kuota hari ini lagi pada hari kerja berikutnya; bukti/revisi yang sama dipakai selama retensi masih berlaku. Pemohon tidak memilih jadwal mendatang.
6. Hasil yang disetujui otomatis mengunduh PDF setelah backend menyatakan SLIK_READY. Halaman hasil memantau kasus manual setiap lima detik, tanpa request paralel; unduhan dimulai ketika helpdesk menyetujui dan laporan tersedia. Menu Permohonan saya tidak ada. Simpan nomor APP untuk membuka hasil melalui Status layanan jika meninggalkan halaman. Tombol unduh ulang tersedia jika browser memblokir unduhan otomatis. Tidak ada email pengiriman hasil. PDF memerlukan cookie browser pemilik yang sama dan keputusan/revisi/expiry valid. Mengetahui APP ID sendiri tidak memberi akses. Menghapus cookie atau memakai perangkat/browser lain kehilangan akses; tidak ada pemulihan identitas/email yang belum diverifikasi. Cookie bukan bukti identitas atau kewenangan resmi.

## Helpdesk dan admin

Buat akun tanpa sandi bawaan/credential dalam Git:

```bash
npm run user:create -- --login helpdesk-demo --role helpdesk
npm run user:create -- --login administrator-demo --role admin
```

Perintah meminta sandi di terminal, tidak di argument/log. Pilih Akses petugas untuk login operator. Cookie petugas terpisah dari cookie pemohon; logout petugas tidak menghapus permohonan browser. Helpdesk melihat kasus yang belum diambil atau ditugaskan kepadanya. Klik kasus → Mulai pemeriksaan pada tanggal dan jam yang dipesan. Periksa foto, bukti proof, hasil model, alasan, identitas resmi dan kewenangan. Keputusan harus menyebut revisi bukti yang sedang diperiksa dan catatan dasar. Tombol identitas/kewenangan mencatat **pemeriksaan manual demo**; tidak mengubah hasil Dukcapil menjadi resmi. Persetujuan produksi ditahan jika prosedur wajib belum terpenuhi.

Administrator melihat volume setiap state, antrean, observasi retry, gangguan teknis, rata-rata latensi verifikasi dan waktu tunggu, runtime/fallback; ia mengubah kapasitas/jadwal/retensi dan ambang. Admin tidak boleh membuat keputusan helpdesk melalui tombol review. Untuk mencoba capture sebagai admin di demo, hanya permohonan yang dimiliki akun itu sendiri dapat diakses; admin tidak mendapatkan nonce milik pemohon lain. Akun integration hanya untuk backend induk, tidak untuk UI pemohon atau inference worker.

## Kapasitas dan retensi

Default [config/capacity-demo.json](../config/capacity-demo.json): Asia/Jakarta, Senin–Jumat, 08:00–17:00, 10 kasus/hari, horizon 14 hari, retensi bukti 21 hari, keputusan berlaku 24 jam setelah persetujuan. Hari libur harus diisi admin; daftar default kosong **bukan kalender libur resmi**. Pemilihan jadwal yang melampaui retensi bukti ditolak, bukan memperpanjang retensi diam-diam.

Transaksi SQLite `BEGIN IMMEDIATE` / PostgreSQL advisory transaction lock menyatukan cek kapasitas, kasus unik, perubahan jadwal, idempotency dan update aplikasi. Hanya kasus manual memakai kuota. Kasus selesai tetap dihitung sebagai kapasitas yang digunakan hari itu; pembatalan sebelum pemeriksaan mengembalikan kapasitas. Kasus IN_REVIEW/COMPLETED tidak dapat dibatalkan/dipindahkan sebagai reservasi biasa. Jika slot terakhir habis, admission menyimpan `CAPACITY_FULL`; bukti dipertahankan dan UI menawarkan pemeriksaan kuota hari ini lagi pada hari kerja berikutnya. Kalender tersedia bagi operator untuk melihat kapasitas; endpoint reserve/move dipertahankan untuk klien terautentikasi legacy, sedangkan browser publik hanya menerima tanggal hari ini. Idempotency key dengan payload berbeda ditolak.

Bukti aktif terdiri dari foto dokumen, selfie, foto memegang KTP, hasil verifikasi/pengikat proof, identitas dan paling banyak tiga frame gerakan yang relevan. Video penuh tidak disimpan. Catatan review juga tersegel. Metadata terikat `application_id`, HMAC `subject_id`, `capture_revision`, `policy_version`, jenis dan expiry melalui AEAD AES-GCM. Subjek tidak diindeks dengan SHA-256 NIK tanpa kunci. Payload permohonan, hasil model historis, receipt/contact dan display login juga tersegel; lookup akun memakai HMAC. Key-check menolak key berbeda pada startup. Migrasi menyegel payload legacy dan melakukan checkpoint/VACUUM SQLite setelah perubahan agar halaman lama tidak tetap plaintext. Backup/WAL historis di luar aplikasi tetap mengikuti kebijakan penyimpanan infrastruktur. Kunci lokal 32 byte tersimpan `data/.local.key` dengan mode 0600; folder data dan .env diabaikan Git. **Backup DB beserta kunci**, atau bukti tidak dapat dibaca setelah pindah komputer. Production wajib key dari secret manager, dibagi aman ke instance yang berwenang; rotasi key/migrasi ciphertext membutuhkan prosedur operasional tersendiri, bukan mengganti key tanpa migrasi.

Penghapusan ciphertext kedaluwarsa berjalan berkala; `npm run evidence:purge` tersedia untuk pekerjaan retensi. Metadata/audit tanpa foto/NIK lengkap tetap dipertahankan. URL bukti tidak publik/tidak berisi token; setiap akses memerlukan kapabilitas browser atau sesi petugas dan otorisasi, dicatat dalam audit, dan `no-store`. Adapter S3 memakai bucket privat dengan public access block dan ciphertext aplikasi; konten diproksi melalui backend yang mengotorisasi, tanpa public/presigned link. Pemindahan bukti ke storage privat tidak memberi worker AI akses SLIK.

## Keputusan, perubahan bukti dan SLIK

Bukti baru/retake menaikkan revisi permohonan, membatalkan keputusan/hasil aktif dan reservasi lama dalam transaksi; bukti tahap lain dalam sesi kamera yang masih valid tetap dipakai dan dicocokkan ulang. Respons capture usang ditolak. Hasil historis lama tidak otomatis menjadi keputusan baru yang berwenang.

Handoff pendaftaran mengambil identitas dari bukti server dan menolak nama browser yang berbeda. Tidak memerlukan sesi kamera aktif. Adapter SLIK memeriksa pemilik, keputusan, revision, subject HMAC, expiry, kewenangan, kanal dashboard dan bukti sebelum fetch. Stable issuance ID + unique(application,revision), lease 60 detik dan token attempt mencegah retry menghasilkan laporan baru atau respons attempt lama mengganti hasil baru. Adapter downstream resmi **harus** menjamin idempotensi ID ini, termasuk setelah timeout ambigu. Failure tetap SLIK_PENDING; tidak ada janji selesai dalam hitungan detik.

REJECTED berlaku pada permohonan ini. Ada informasi bantuan/peninjauan keberatan, tanpa pemblokiran permanen orang. Sinyal PAD yang melanggar aturan keamanan tidak masuk antrean helpdesk biasa; classifier ViT tetap advisory. Demo belum menyediakan sistem tiket keamanan/appeal eksternal: pesan tidak dikirim dan peninjauan dilakukan lewat host/helpdesk yang berwenang.

## Laporan contoh iDeb

Laporan demo mengikuti susunan panduan iDeb pengguna: pencarian, data pokok debitur perseorangan, ringkasan fasilitas, rincian kredit, riwayat 12 bulan, agunan/penjamin dan legenda. Generator ReportLab di backend mengirim application/pdf dengan Content-Disposition attachment, tanpa window.print. Nama/NIK/tanggal lahir mengikuti EvidenceStore server, bukan field browser. Yang diacak hanya fasilitas/nominal/riwayat keuangan; kolom identitas yang tidak tersedia tidak diisi data palsu. Semua halaman bertanda DEMO - BUKAN INFORMASI DEBITUR RESMI, dan sumber identitas resmi tetap belum terverifikasi.

Financial generator menggunakan seed dari stable issuance ID (bukan NIK), dan payload final disimpan terenkripsi. Unduh ulang/idempotent retries mempertahankan financial data, bukan mengacak ulang untuk issuance yang sama. Laporan lama schema v2 dibentuk ulang satu kali ke v3 pada akses oleh pemilik dengan keputusan yang masih valid, untuk menyelaraskan identitas dengan bukti server. Posisi data September 2026 adalah contoh tetap. Generator bukan layanan SLIK resmi dan model KYC tidak menggunakan financial RNG.
