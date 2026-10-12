# Validasi lokal V3 — 12 Oktober 2026

Jalankan `npm run setup:test`, `npm run check`, `npm test`, dan `npm run benchmark:coreml` pada Mac arm64. Bobot nyata harus tersedia melalui `npm run setup`; checksum tetap diperiksa. Semua fixture protokol/UI diberi label, tidak menjadi preset keputusan pengguna.

## Hasil pengujian

- `npm run check`: lulus pemeriksaan syntax Python dan JavaScript.
- `npm test` (3.0.2): **149 pytest lulus, 2 dilewatkan; 40 tes Node lulus**. Satu peringatan dependency Starlette/httpx tentang deprecation, bukan kegagalan tes.
- Dua skip: native NVIDIA CUDA (Mac tidak memiliki CUDA EP/GPU) dan PostgreSQL server (tidak ada MOCK_ID_POSTGRES_TEST_URL). Bobot/model lokal tersedia; tidak ada tes model dilewatkan karena bobot hilang.
- CPU/CoreML Swin V2 benar-benar dijalankan: parity logits maksimum `4.291534423828125e-06`, probabilitas `8.226236358765959e-10`. Profiler mengamati 2050 event CoreML dan 4760 event CPU pada profil hybrid, dibanding CPU-only 10280 event. Median tujuh warmed calls CPU 0,2300 detik; CoreML 0,2419 detik. Tiga varian gambar astronaut publik. Angka ini bukan FPS kamera, atribusi fisik GPU/ANE, akurasi identitas atau ketahanan spoof.

## Perilaku yang dibuktikan

Boundary routing 74,99 / 75 / 94 / 94,99 / 95 / 100, skor asli sebelum pembulatan, mandatory gagal dan calibration production hold. Capture/technical tidak menjadi score nol/reject. Nonce/proof/selfie binding, frame replay, capture revision, retake dan attempt/rate limits existing tetap diuji.

Decision/case/evidence setelah restart, approval manual menuju synthetic SLIK tanpa sesi kamera aktif, rejection/expiry tidak menerbitkan, canonical identity dan server subject HMAC, revocation evidence baru, lease/retry downstream tanpa duplikasi. AEAD tamper/retention/binding, key mismatch, sealing legacy dan respons idempotency, tanpa plaintext NIK indeks.

Browser guest tanpa login, HttpOnly ownership, login petugas terpisah, logout petugas tidak menghilangkan ownership pemohon, cross-owner/operator/integration scope. Auto today admission tanpa tombol reservasi, dua pemohon berebut slot terakhir, full lalu retry hari kerja berikutnya tanpa capture baru, weekend/holiday/hours, cancel/rebook tanpa respons reservasi lama yang fiktif. Kalender/move/idempotency klien terautentikasi legacy tetap diuji.

Queue/backpressure/timeout mempertahankan model/session lock sampai pekerjaan native selesai. Worker CPU memakai tensor dan bobot Swin nyata, parity dengan inferensi lokal; remote transport/checksum/TLS/error diuji. CUDA selection/fallback, PostgreSQL SQL adapter, Redis registry dan private S3 memakai unit fixtures; **bukan pengujian layanan deployment nyata**.

## Pemeriksaan UI dasar (V3.0)

Database QA disposable terpisah dari data pemohon normal. Fixture manual dan review menggunakan foto astronaut publik dan skor protokol yang secara eksplisit diinjeksi hanya untuk QA. Ia membuktikan status/otorisasi/UI, bukan model liveness yang berhasil pada orang nyata. Jam/kuota QA 00:00–23:59 dan dua slot juga merupakan konfigurasi fixture, bukan default/SOP OJK.

Browser: beranda → Pendaftaran → Perseorangan → OCR tanpa form login; OCR native pada gambar kartu teks sintetis menghasilkan NIK 1234567890123456, PEMOHON TEST, lahir 1990-01-01, alamat JALAN UJI. Kartu tanpa potret ini tidak diuji sebagai final KYC yang lolos. Kasus protokol berbeda → auto quota → helpdesk memulai/review → SLIK_READY → pemilik browser melihat laporan baru yang memuat pencarian, data pokok, ringkasan, dua fasilitas, riwayat 12 bulan, agunan dan penjamin.

Layout laporan diperiksa pada viewport normal dan **390 × 844**. Tidak ada overflow halaman (`clientWidth=scrollWidth=390`); field menjadi satu kolom, tabel bulanan scroll horizontal. Viewport kemudian dikembalikan. Cetak memakai CSS print dan dialog browser; belum diuji ekspor PDF pada seluruh browser/perangkat. Kamera fisik pengguna tidak diaktifkan pada QA ini.

## Batas hasil

Tidak ada pengukuran accuracy/APCER/BPCER/populasi/aging/deepfake/injection yang dapat diklaim dari tes ini. Demo score belum terkalibrasi. Uji GPU nyata, PostgreSQL concurrency multiinstance, S3/Redis deployment, kanal resmi, audit/SOP dan kalibrasi produksi masih harus dilakukan dalam lingkungan yang disetujui. Tidak ada deployment atau panggilan layanan resmi OJK/Dukcapil selama development ini.

## Pembaruan 3.0.1: liveness dan PDF

Tes baru memeriksa lebih dari tiga restart/retake liveness yang belum menghasilkan proof tanpa menghapus dokumen atau meloloskan frame/token lama. Detector miss singkat tidak menghasilkan proof; gap panjang/penutup/spoof tetap mereset action/menolak. Final-verification attempt limits, replay, nonce dan session expiry tetap berlaku.

PDF native dibaca pypdf dan dirender Poppler, seluruh halaman ditinjau untuk tabel, wrapping, watermark dan footer. Pengujian endpoint memastikan owner-only, keputusan expired/pending/revoked tidak mengunduh, dan revocation selama render tetap ditolak. Financial RNG berbeda untuk issuance berbeda, tetap sama untuk issuance yang sama; nama/NIK/tanggal lahir/alamat tetap dari bukti server. Adapter dengan identitas salah ditahan dan laporan v2 diperbarui sekali ke canonical identity.

Browser QA pada hostname localhost terpisah dari preview pengguna 127.0.0.1: seeded protocol fixture pada DB disposable. Memasukkan APP ID fixture di Status layanan memicu unduhan PDF otomatis yang benar-benar tersimpan oleh browser, tanpa menekan tombol unduh/cetak. Ini bukti transport/UI, bukan kelulusan AI pada webcam nyata.

Validasi akhir 3.0.1: npm run check dan npm test lulus (149 Python + 30 Node; 2 skip lingkungan). Browser mengunduh PDF empat halaman pada fixture penerbitan tiga fasilitas; nama/NIK/tanggal lahir tepat, isi keuangan acak. Reload halaman tidak mengirim ulang PDF secara otomatis; unduh ulang eksplisit tetap tersedia.

## Pembaruan 3.0.2: regresi pengiriman frame kamera

Perbandingan dengan `origin/main` pada commit `8c41958` menunjukkan detektor YuNet dan layanan visibility yang sama. Regresi ditemukan pada filter kualitas browser versi 3: ia menghentikan preview dan frame streaming liveness saat blur/cahaya/posisi dianggap belum siap. Posisi wajah yang disimpan dari frame lama juga dapat memblokir request yang seharusnya memperbarui posisi itu. Kualitas dan posisi liveness kini diperiksa pada frame baru oleh server; label kotak membedakan wajah ditemukan dan kualitas siap.

Tes Node menjalankan fungsi `monitorCamera`, `recordChallenges` dan `drawFaceDetection` dari sumber aplikasi dalam VM dengan respons protokol, tanpa kamera fisik. Tes memeriksa pengiriman kontinu saat hint lokal gagal, dua pemeriksaan server sebelum mulai, peringatan masker yang tetap menghalangi mulai, pemulihan detector miss, nomor frame/nonce berurutan, satu request aktif, penolakan server, selfie yang tepat sesuai `selfie_seq`, respons generasi kamera lama, dan label wajah saat kualitas belum siap. Dokumen/foto memegang KTP tetap memerlukan gate kualitas lokal dan recheck server. Kotak wajah lama tidak menjadi veto kualitas baru.

Inferensi model nyata, penolakan foto datar bergerak, replay/proof binding, kontinuitas wajah dan reset setelah penutup/spoof tetap dicakup oleh suite Python. Tidak ada perubahan threshold model atau pelolosan otomatis dari UI. Pengujian protokol ini membuktikan perbaikan alur pengiriman; belum mengukur akurasi atau FPS pada kamera fisik pengguna.

Validasi 3.0.2: `npm run check` dan `npm test` lulus (149 Python, 40 Node, 2 skip lingkungan). Empat tes preview/overlay dijalankan terhadap sumber `app.js` sebelum perbaikan (`c6b6421`) dan semuanya gagal sebagaimana diharapkan; keempatnya lulus pada sumber baru.
