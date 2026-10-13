# Validasi lokal V3 — 12 Oktober 2026

Jalankan `npm run setup:test`, `npm run check`, `npm test`, dan `npm run benchmark:coreml` pada Mac arm64. Bobot nyata harus tersedia melalui `npm run setup`; checksum tetap diperiksa. Semua fixture protokol/UI diberi label, tidak menjadi preset keputusan pengguna.

## Hasil pengujian

- `npm run check`: lulus pemeriksaan syntax Python dan JavaScript.
- `npm test` (3.0.4): **161 pytest lulus, 2 dilewatkan; 46 tes Node lulus**. Satu peringatan dependency Starlette/httpx tentang deprecation, bukan kegagalan tes.
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

## Pembaruan 3.0.3: PAD meragukan dan UI tanpa login petugas

Input RGB, normalisasi ImageNet, resize dan kelas live=0/spoof=1 dibandingkan dengan sumber CVPR yang dipin dan sesuai; tidak ada bukti kesalahan label/konversi CoreML dari screenshot pemohon. Screenshot berisi overlay/kompresi bukan frame webcam mentah, dan tidak dipakai sebagai data kalibrasi atau fixture akurasi.

Mode demo tanpa artefak kalibrasi yang disetujui memisahkan bukti gerakan dan keputusan PAD. Model PAD tetap dijalankan; skor rendah tetap disimpan dan kontrol PAD tetap gagal. Gerakan netral/kedip/putar/senyum dan kontinuitas/proof masih wajib. Hasil PAD meragukan dengan bukti/identitas lengkap masuk MANUAL_PENDING, termasuk bila raw routing score rendah, mengambil kuota hari ini, dan tidak dapat mengunduh PDF sebelum review. Produksi dan profil terkalibrasi memakai aturan PAD ketat. PAD foto memegang KTP kini juga diperiksa pada final verify, sehingga capture foto itu tidak bisa menyembunyikan sinyal yang memerlukan review.

Tes protokol memeriksa warning review yang tetap tampak, masker tidak diloloskan oleh review PAD, proof gerakan yang tidak mengklaim PAD lulus, produksi ketat, gerakan gagal yang tidak berubah menjadi review, kuota hari ini, PDF tertahan, syarat proof/identitas, dan PAD pada foto memegang KTP. Tes model nyata/foto datar/replay existing tetap lulus. Frame preview dan tantangan memakai JPEG 0.95 hingga 1920 px tanpa upscaling; tes klien memeriksa kontrak encoding yang sama dan backpressure satu request.

UI tidak menampilkan akses/login/workspace petugas. Bootstrap browser tetap memakai cookie guest yang terpisah; API petugas/integrasi tetap berotorisasi dan tidak dibuka menjadi operator anonim. Tes Node menjalankan deep-link dan bootstrap aktual. Browser QA pada database disposable localhost:4187 memverifikasi beranda tanpa login, link lama #account kembali ke #home, lalu Pendaftaran dengan tiga jenis debitur. Kamera pemohon tidak diaktifkan. Bukti tampilan: `outputs/public-ui-without-staff-login.png` di workspace chat.

Validasi 3.0.3: `npm run check` lulus; 158 Python dan 44 Node lulus, 2 skip lingkungan. Setelah koreksi bootstrap tombol help yang dihapus dari shell, browser diperiksa ulang dan seluruh tes Node serta syntax check lulus. Pengujian ini membuktikan routing/status/otorisasi, bukan peningkatan akurasi Swin terhadap wajah pemohon; kalibrasi webcam masih diperlukan.

## Pembaruan 3.0.4: Dukcapil dianggap lolos pada demo

Adapter mock mengembalikan passed/simulated dengan flag identitas demo tersendiri. Tes memeriksa mode produksi tetap memilih adapter resmi yang unavailable/pending, hasil pipeline/check Dukcapil passed dengan identitas resmi false, flag lolos simulasi tersimpan pada permohonan dan dihapus setelah capture diganti, serta PAD meragukan tetap manual. Tes UI menjalankan renderer checklist dan panel permohonan aktual: label MOCK · lolos simulasi tampil tanpa klaim validasi resmi dan status manual tidak berubah.

`npm run check` dan `npm test` lulus: 161 Python, 46 Node, 2 skip lingkungan. Tidak ada panggilan Dukcapil resmi, perubahan hasil historis atau pengambilan kamera pengguna pada pembaruan ini.

## Pembaruan 3.1.0: OCR multi-frame, ArcFace dan glare

`npm run check` dan `npm test` lulus: **183 Python, 46 Node, 2 skip lingkungan** (CUDA/PostgreSQL). Bobot nyata baru ArcFace R50 diperiksa checksum; semua tes inference OCR, face/PAD/landmark/penutup/tangan tetap lulus. Tes tambahan memeriksa similarity alignment, RGB normalisasi, embedding invalid, public face blur/downsample vs identitas fixture lain, migrasi ambang, penolakan kalibrasi model yang salah, arsip berchecksum dan ekstraksi satu anggota. Tes glare mencakup patch besar vs speckle/stock berwarna, crop kartu vs latar putih dan penolakan sebelum OCR.

Tes OCR mencakup label rusak tanpa koreksi ejaan pribadi, NIK tanpa tebakan karakter, tanggal lahir yang harus bersumber dari field-nya, susunan box/baris, crop native tanpa upscale, maksimal dua pembacaan ulang ROI, confidence per-field, konsensus frame berbeda, konflik identitas/kartu, buffer kedaluwarsa, retake yang menghapus token, binding foto/token dan replay. Tes Node menjalankan fungsi kamera aktual agar filter kualitas global tidak menghalangi frame baru dan gate dokumen memerlukan bukti konsensus server.

QA browser dilakukan pada server disposable `localhost:4188` dengan kartu sintetis bertuliskan BUKAN KTP. Melalui unggah UI dan inference nyata, form identitas menampilkan 1234567890123456, PEMOHON TEST, 1990-01-01 dan JALAN UJI beserta petunjuk per-field. Kamera fisik pengguna tidak dibuka dan hasil KYC lolos tidak disimulasikan. Screenshot tersedia di workspace outputs/ocr-310-field-review.png. Document Liveness dibatalkan, bukan classifier yang dianggap lulus. Tidak ada benchmark akurasi KTP pengguna/aging/material asli yang dapat disimpulkan dari pengujian ini.

## Pembaruan 3.1.1: workspace operator dan ambang demo 50

`npm run check` dan `npm test` lulus: **198 Python, 48 Node, 2 skip lingkungan**. Boundary 49.999/50/50.001 diuji tanpa pembulatan. Hasil PAD numerik belum meyakinkan dengan skor ≥50 diterima khusus demo, sementara nilai raw/failed controls tetap disimpan. Uji workflow nyata sampai PDF memastikan nama/NIK laporan mengikuti identitas server. NIK berbeda, wajah tertutup, tangan/gerakan gagal, proof/kewenangan tidak sah, capture/technical/attack dan aturan produksi/profil terkalibrasi tetap diuji menahan penerbitan. Tes kuota di bawah 50 tetap memeriksa reservasi atomik hari ini.

Tes UI/API memeriksa akses operator vs cookie publik, admin/helpdesk/guest routing, metadata ambang server dan pengiriman PDF yang tetap dideduplikasi. QA browser pada server disposable dengan database/akun uji terpisah: anonymous dashboard meminta login; login admin memuat ringkasan/antrean/audit/modul, ambang demo ≥50 tampil dari server, logout kembali ke login dan Beranda menyediakan Pendaftaran tanpa login. Kamera pengguna tidak diaktifkan. Screenshot workspace berada di outputs/operator-311-workspace.png dan pratinjau outputs/operator-311-workspace-preview.png di workspace lokal. Tidak ada keputusan biometrik pengguna atau data SLIK resmi dalam fixture.

## Pembaruan 3.1.2: password akun lokal

`npm run check`, `npm run user:password -- --help` dan `npm test` lulus: **209 Python, 48 Node, 2 skip lingkungan**. Sebelas tes password memakai akun/database disposable. Password baru dapat login, password lama ditolak, semua token akun target dicabut, akun/role/ownership tidak berubah, akun lain dan kapabilitas browser tetap valid. Akun tidak ditemukan, panjang invalid, disabled/browser dan dua input berbeda tidak mengubah password. CLI tidak mencetak password dan menolak fallback input terlihat. Limit login yang direset hanya milik akun target. Login yang membaca hash lama lalu beradu dengan reset tidak dapat menghasilkan token valid setelah reset.

Tidak ada password pengguna yang diubah, diminta di chat, atau dimasukkan oleh agen. Tidak ada UI/endpoint HTTP reset publik. Pengguna memasukkan password barunya sendiri melalui terminal saat menjalankan perintah pada clone/data yang sama dengan server.
