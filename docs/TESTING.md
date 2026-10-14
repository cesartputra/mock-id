# Validasi lokal V3 — 12 Oktober 2026

## Audit Ponytail — 14 Oktober 2026

Branch `refactor/ponytail-improvements`: suite penuh final lulus **355 tes Python dan 105 tes JavaScript**, dengan 2 skip lingkungan CUDA/PostgreSQL dan satu peringatan deprecation Starlette/httpx. Syntax/compile dan `git diff --check` lulus.

Empat regresi Python tambahan menguji cancellation antrean yang tetap menahan slot sampai pekerjaan native selesai, antrean penuh yang tidak mengonsumsi sequence/hash, verifikasi dibatalkan yang masih dapat retry dengan nonce baru, dan request dibatalkan versi lama yang tidak menghapus hasil/lock capture versi baru. Enam regresi JavaScript tambahan menguji frame HTTP 429 yang dicoba kembali dengan sequence yang sama, respons sesi lama dan start ganda, retake stale, error setelah akun berubah, hasil lama yang tidak mengarahkan/mengunduh PDF, dan entri validasi JSON yang salah format. Tes lifecycle kamera yang sudah ada juga memeriksa retake yang tidak lagi berlaku tidak membuka kamera.

Kasus failure direproduksi sebelum perbaikan. Fixture protokol mengisolasi concurrency/transport; suite model lokal yang sudah ada tetap dijalankan. Tidak ada data pemohon nyata, webcam pribadi atau backend deployment baru yang dipakai. Cakupan dan risiko tersisa dijelaskan di [catatan audit](PONYTAIL-AUDIT.md).

## Validasi terbaru 3.6.1 — 14 Oktober 2026

Suite penuh Python lulus **351 tes**, dengan 2 skip lingkungan CUDA/PostgreSQL dan satu peringatan deprecation dependency. Suite JavaScript final lulus **99 tes**; teks konfirmasi preflight yang diperiksa regresi tetap dipertahankan. Syntax/compile dan whitespace diff lulus. Tidak ada bobot/dependency baru.

Dua tes API tambahan membuktikan OCR pemohon menolak gambar tanpa receipt pengambilan otomatis sebelum inferensi atau penambahan percobaan, dan receipt sah terikat digest gambar serta sekali pakai. Tiga tes JavaScript baru memeriksa tiadanya file picker di kedua halaman capture, penolakan input galeri/hasil kamera yang belum lengkap tanpa mengganti state, dan penyimpanan blob asli serta receipt dari capture yang sudah diperiksa. Tes lifecycle kamera diperluas untuk rasio 1920×1080, resize ke 720×1280, kelas dialog/portrait dan cleanup. Regresi CAPTCHA, pemilik/versi sesi, pencahayaan dan gesture tetap lulus.

QA browser memakai harness `.cache/camera361-ui` dengan fungsi kamera/view/CSS aktual, potret astronaut publik dan kartu sintetis bertanda **KARTU UJI — BUKAN KTP**, tanpa webcam, KTP atau data pemohon. Input file berjumlah nol. Preview desktop terukur sekitar 737×415 px pada browser uji, dengan rasio video asli 16:9, instruksi di samping, dan bingkai wajah/KTP terpisah sekitar 25 px. Backdrop tetap putih. Pada 390×844 layout menjadi satu kolom tanpa overflow horizontal; ukuran browser dipulihkan setelah QA. Screenshot chat: `outputs/app-361-camera-only.jpg`, `app-361-camera-large.jpg`, dan `app-361-camera-mobile.jpg`. Ini validasi UI/protokol; tidak membuktikan attestation webcam atau peningkatan akurasi biometrik.

## Validasi terbaru 3.6.0 — 14 Oktober 2026

Suite penuh final lulus **349 tes Python dan 96 tes JavaScript**, dengan 2 skip lingkungan CUDA/PostgreSQL dan satu peringatan deprecation dependency. Syntax/compile dan whitespace diff lulus. Tidak ada bobot atau dependency baru.

Lima belas kasus Python tambahan memakai piksel sintetis untuk memeriksa batas luminans 35/36, wajah/area panduan gelap dengan latar terang, area panduan terang dengan latar gelap, precheck selfie/holding/OCR tanpa memuat atau menjalankan model, pemeriksaan crop wajah sebelum atribut/tangan/PAD, tidak adanya selfie/PAD/bukti gerakan dari frame gelap, retry tahap yang benar pada verifikasi akhir, serta jeda tanpa gambar yang terikat nonce/urutan/waktu sesi. Jeda mempertahankan gerakan selesai dan tidak menghapus sinyal spoof sebelumnya atau menambah frame/bukti. Tiga tes preview PAD lama sekarang menggunakan foto astronaut publik sebagai input piksel valid, dengan keluaran model tetap berupa fixture protokol.

Delapan tes JavaScript tambahan memeriksa bobot RGB, ambang gelap dan hysteresis pemulihan, pembacaan area video asli, penahanan foto/unggah sebelum inferensi, respons terang yang terlambat ketika kamera sudah gelap, pemulihan warning tanpa mengotorisasi capture, jeda liveness tanpa gambar/nomor frame yang terlewati, pembatalan di tengah jeda, serta lifecycle lightbox putih dan penghentian timer/track saat ditutup. Regresi blur lokal yang tidak menghalangi pemeriksaan kualitas ROI server tetap lulus.

QA browser menggunakan harness terisolasi `.cache/lightbox360-ui`, fungsi kamera/CSS/LuminanceCheck aktual dan stream canvas sintetis dengan foto astronaut publik; tidak mengakses webcam, KTP, CAPTCHA, data pemohon atau OJK. Surround, dialog, dan backdrop terbukti `rgb(255, 255, 255)`; pergantian terang/gelap menampilkan pesan yang diminta. Ukuran 390×844 tidak memiliki overflow horizontal (`clientWidth=scrollWidth=390`), warning dan tombol Batal terbaca. Ukuran browser dipulihkan. Screenshot tersimpan pada workspace chat: `outputs/app-360-lightbox-bright.jpg`, `app-360-lightbox-dark.jpg`, dan `app-360-lightbox-mobile.jpg`. Pengujian ini memverifikasi perilaku kualitas/transport/state dan layout, bukan ukuran perubahan pencahayaan fisik atau kalibrasi biometrik pada seluruh kamera/warna kulit.

## Validasi terbaru 3.5.1 — 14 Oktober 2026

Suite penuh lulus **334 tes Python dan 88 tes JavaScript**, dengan 2 skip lingkungan CUDA/PostgreSQL dan satu peringatan deprecation dependency. Syntax/compile dan whitespace diff lulus. Tes CAPTCHA server memeriksa bahwa jawaban salah langsung membatalkan challenge lama, puzzle baru berbeda, pemilik lain tidak terpengaruh, serta receipt tetap terikat pemilik dan sekali pakai.

Tes class UI aktual memeriksa reset slider/potongan ke nol, gambar/challenge baru otomatis, persetujuan yang dipertahankan, challenge kedaluwarsa yang diperbarui, server error tanpa loop refresh, receipt invalid yang tidak melanjutkan, serta respons sukses setelah pembatalan yang diabaikan. Integrasi class dengan `newFlow` membuktikan jawaban sah otomatis membuat tepat satu sesi, tanpa tombol/click lanjut. Pengujian pointer-release dan debounce keyboard tetap lulus.

QA browser memakai database terpisah `.cache/captcha351-data`: pendaftaran → persetujuan → CAPTCHA. Puzzle/instruksi baru dan ketiadaan tombol Lanjut ke verifikasi diperiksa melalui UI; screenshot `outputs/app-351-captcha-auto.jpg` tersimpan pada workspace chat. Puzzle browser tidak diselesaikan; alur salah/benar dan pembuatan sesi diuji pada fixture protokol/API disposable. Tidak ada KTP, kamera pribadi atau layanan CAPTCHA eksternal yang dipakai.

## Validasi terbaru 3.5.0 — 14 Oktober 2026

Suite penuh lulus **333 tes Python dan 84 tes JavaScript**, dengan 2 skip lingkungan CUDA/PostgreSQL dan satu peringatan deprecation dependency. Syntax/compile check juga lulus. Delapan belas tes Python baru mencakup penghapusan foto yang mempertahankan identitas/hasil/PDF, seluruh revisi serta sesi RAM, penghapusan penuh dan isolasi permohonan lain dengan owner/NIK sama, reservasi/hasil/registrasi/cache terkait, otorisasi admin, konfirmasi/versi stale, native work/PDF aktif, storage tidak tersedia, crop perspektif native terenkripsi dan retensi/binding, idempotensi crop lama, penolakan pemulihan foto yang dihapus saat OCR berjalan, serta hasil gagal yang tetap dapat ditelusuri lewat pengikat sesi setelah sesi/bukti kedaluwarsa. Setelah penguatan fixture hasil orphan, seluruh 18 tes operator dijalankan kembali dan lulus.

Sembilan tes JavaScript baru mencakup navbar/peran, daftar permohonan selesai, escaping teks, foto asli/crop/perbesar, placeholder foto terhapus tanpa request gambar, dialog default foto saja dengan konfirmasi satu APP, payload versi server, refresh hasil tanpa mengunduh PDF operator, respons cleanup stale dan respons crop yang tidak mengganti permohonan lain. Regresi otorisasi publik/operator yang sudah ada tetap lulus.

QA browser memakai server dan database `.cache/operator350-data` terpisah: kartu sintetis bertanda **KARTU UJI — BUKAN KTP**, potret astronaut publik, dan hasil biometrik fixture berlabel. OCR native benar-benar dijalankan untuk memilih crop kartu. UI menunjukkan foto latar utuh di sebelah crop tanpa latar, perbesar crop, dialog jumlah data dan dua pilihan penghapusan. Dialog diperiksa lalu dibatalkan; perilaku penghapusan dijalankan pada database disposable melalui tes API, bukan data pemohon nyata. Navbar berada di header. Viewport 390×844 tidak overflow halaman; navbar/tabel scroll dan galeri satu kolom. Ukuran browser dipulihkan setelah QA. Screenshot berada di outputs/app-350-operator-dashboard.jpg, app-350-ktp-crop.jpg, app-350-clean-data.jpg dan app-350-operator-mobile.jpg pada workspace chat. Tidak ada KTP/kamera pribadi atau pengajuan ke OJK pada pengujian ini.

## Validasi terbaru 3.4.1 — 14 Oktober 2026

Suite penuh lulus **315 tes Python dan 75 tes JavaScript**, dengan **2 skip lingkungan** (CUDA native / server PostgreSQL) dan satu peringatan deprecation Starlette/httpx. Pemeriksaan sintaks Python/JavaScript dan whitespace diff lulus. Tidak ada model atau dependency baru.

Empat puluh tes Python baru memeriksa contoh skor 76,98 dengan kontrol PAD gagal yang tetap tercatat, batas 49,999/50/50,001, kewajiban identitas/wajah/gerakan/kualitas/proof/kewenangan, penolakan PAD hilang/duplikat/tidak tersedia/invalid, serta produksi/profil terkalibrasi yang tetap ketat. Penilaian ulang kasus lama diuji dari bukti terenkripsi hingga PDF dengan identitas server: slot manual dilepas, keputusan/penerbitan idempoten, bytes bukti asli tidak berubah, pemilik lain/versi lama/retensi habis/binding salah/attestation hilang/kasus sedang diperiksa tetap ditolak.

Tiga tes JavaScript baru memeriksa penjelasan routing dan tombol kasus lama, POST yang hanya membawa versi capture, pencegahan klik ganda, pemantauan unduhan, serta respons lama yang tidak menggambar ulang atau mengunduh PDF setelah halaman/pemilik berubah.

QA browser memakai server/database terisolasi dan fixture protokol berlabel **data/skor sintetis**: kasus 76,98 berstatus `MANUAL_SCHEDULED` diproses melalui tombol UI hingga `SLIK_READY`, tracker selesai dan unduhan otomatis terpicu. Nilai/rincian PAD rendah tetap terlihat pada hasil. Template halaman verifikasi dengan CSS aktual diperiksa: garis judul merah 3 px dan tepi atas panel abu-abu 1 px, tanpa garis merah ganda. Screenshot chat tersimpan di `outputs/app-341-score-pass.jpg` dan `outputs/app-341-red-line.jpg`. Ini bukti routing/otorisasi/layout/transport PDF, bukan ukuran akurasi biometrik; tidak ada KTP atau webcam pribadi yang dipakai.

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

## Pembaruan 3.1.3: daftar akun lokal

`npm run check`, pemeriksaan sintaks wrapper Node, `npm run user:list` dan `--help` lulus. Suite terarah akun/password/workflow: **60 tes Python lulus**. Tiga tes baru memastikan akun password/role/status dapat dibaca dengan filter, kapabilitas browser dikecualikan, password/hash tidak ditampilkan, password/sesi/audit/evidence tidak berubah, serta database/folder/kunci tidak dibuat ketika database tidak ada. Full regression sebelumnya pada 3.1.2: 209 Python, 48 Node, 2 environment skip; tidak ada perubahan model atau alur capture pada pembaruan listing ini.

## Pembaruan 3.3.0 Persetujuan dan CAPTCHA puzzle

Pada 14 Oktober 2026, suite Python penuh lulus **257 tes, 2 environment skip**, dengan satu peringatan deprecation Starlette/httpx. Suite JavaScript akhir lulus **63 tes**, tanpa skip/gagal; syntax/compile check lulus. Setelah penyesuaian checkbox menjadi dua tahap dan pemeriksaan slider otomatis, seluruh tes JavaScript serta enam tes Python preflight dijalankan kembali dan lulus.

Tes preflight memeriksa penolakan sesi pemohon tanpa persetujuan/CAPTCHA, penyimpanan attestation server, gambar PNG lokal tanpa jawaban numerik dalam respons, jawaban salah, expiry, pembaruan challenge, isolasi pemilik, konsumsi receipt atomik/sekali pakai, dan sesi baru versus pengambilan ulang tahap. Fixture memakai pemilik/database disposable dan jawaban dari state server khusus pengujian; tidak menilai ketahanan CAPTCHA terhadap bot tingkat lanjut.

Tes UI menjalankan class yang dikirim ke browser: checkbox dan Saya Mengerti mendahului permintaan puzzle; consent/puzzle wajib sebelum sesi dibuat; refresh/back/cancel membatalkan receipt/respons lama; expiry menonaktifkan lanjut. Pointer drag tidak diperiksa selama masih ditahan, release memeriksa posisi akhir sekali, keyboard input memakai debounce, posisi salah yang tidak berubah tidak dikirim berulang, dan pembatalan menghapus pemeriksaan tertunda.

QA browser memakai server/data terisolasi pada localhost. Dialog pernyataan, checkbox, pengaktifan Saya Mengerti, dan tampilan CAPTCHA tanpa tombol Periksa puzzle diperiksa pada desktop 1280×900 dan mobile 390×844. Tombol bawah tetap terlihat saat isi dialog digulir. Tidak ada KTP atau kamera pribadi yang digunakan dalam QA. Screenshot berada di workspace chat: outputs/app-330-consent-desktop.jpg dan outputs/app-330-captcha-mobile.jpg.


## Pembaruan 3.4.0 Layout proses dan tracker dokumen

Pada 14 Oktober 2026, suite penuh lulus **275 tes Python, 2 environment skip**, dengan satu peringatan deprecation Starlette/httpx. Suite JavaScript final lulus **72 tes**, tanpa skip/gagal; pemeriksaan sintaks/compile dan diff whitespace lulus. Seluruh tes JavaScript dijalankan ulang setelah penyempurnaan pembaruan sebagian tampilan status dan perlindungan respons pencarian yang sudah kedaluwarsa.

Delapan belas tes Python baru mencakup semua status workflow, waktu dari riwayat versi bukti terbaru, PDF pending versus siap, perbaikan capture versus penolakan, gangguan sebelum bukti diterima, formulir mock yang tidak memperoleh hasil verifikasi/PDF, kepemilikan status dan identitas, keputusan kedaluwarsa, identitas KTP server, status pendaftaran terhubung setelah penerbitan, serta invalidasi keputusan ketika bukti diganti. Snapshot publik tidak memuat riwayat/evidence operator.

Sembilan tes JavaScript baru menjalankan renderer dan fungsi lookup/polling aktual: semantik tahapan/legenda, escaping teks server, status tidak dikenal yang tidak dianggap selesai, pencarian APP/DEMO yang tetap di halaman status, progres permohonan terhubung, respons lama/berpindah halaman/pemilik, identitas dari endpoint server, unduhan hanya saat PDF ready, dan pembaruan yang mempertahankan node/fokus pencarian serta menghindari render pada status yang tidak berubah.

QA browser memakai database terisolasi `.cache/layout-ui-data`, kontak contoh `example.com`, NIK sintetis, serta fixture protokol yang berlabel bukan hasil inference. Formulir, konfirmasi dokumen, modal berhasil, dan pencarian status diperiksa melalui UI. Reservasi manual benar-benar memakai API demo dan tetap berada pada halaman status. Desktop 1280×900 serta ponsel 390×844 diperiksa; tracker berubah dari horizontal menjadi vertikal, lebar dokumen sama dengan viewport pada ponsel. Tidak ada KTP/kamera pribadi, pengajuan OJK, atau pengiriman email dalam QA. Screenshot chat berada di `outputs/app-340-registration-desktop.jpg`, `outputs/app-340-documents-desktop.jpg`, `outputs/app-340-status-desktop.jpg`, dan `outputs/app-340-status-mobile.jpg`. Pengujian protokol ini tidak mengukur akurasi biometrik.
