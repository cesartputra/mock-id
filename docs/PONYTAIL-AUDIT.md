# Audit Ponytail — 14 Oktober 2026

Branch `refactor/ponytail-improvements` dibuat dari branch aktif `feat/camera-only-large-preview`, commit `1c68868`, setelah fetch origin dan pemeriksaan working tree yang bersih. Audit terarah pada capture, antrean inferensi, retry, respons API, navigasi pemohon, akses operator, penyimpanan bukti dan penerbitan PDF. Perubahan diterapkan pada helper/controller yang sudah ada; tanpa dependency, endpoint atau migrasi baru.

| Temuan | Perbaikan konkret |
|---|---|
| Pembatalan request meninggalkan `processing=True` setelah pekerjaan native selesai. | Antrean menangani cancellation dengan lifecycle yang sama seperti timeout: pekerjaan/slot tetap dimiliki sampai selesai, lalu flag sesi dilepas. Cancellation tetap diteruskan. |
| HTTP 429 antrean penuh sudah menambah sequence/hash frame, sehingga retry frame yang sama ditolak. | Validasi/penerimaan frame dilakukan setelah masuk antrean. Browser menunggu dua detik dan mencoba nomor frame yang sama dengan gambar terbaru; batas 90 detik tetap berlaku. |
| Verifikasi dibatalkan setelah nonce dikonsumsi tidak memiliki hasil technical untuk `/retry`. Cleanup request lama juga bisa menyentuh versi capture baru. | Recovery menyimpan retry technical tanpa menerbitkan keputusan, mempertahankan bukti yang sudah lolos, dan memeriksa revision sebelum mengubah hasil/lock. |
| Respons sesi/retake terlambat bisa mengubah alur setelah navigasi/akun berganti; pembuatan sesi juga bisa dimulai ganda. | Guard navigasi/akun dan flag capture yang sudah ada dipakai sampai request selesai. Caller retake berhenti bila alur sudah berubah; error lama tidak merender ulang halaman, mengarahkan pengguna atau memicu PDF. |
| Detail validasi JSON berupa null/angka atau lokasi yang salah format bisa melempar TypeError dan menutupi HTTP 422. | Parser bersama mengabaikan entri tidak sah dan mempertahankan pesan fallback/status HTTP. |

Duplikasi yang dihapus: penyimpanan/pemulihan sementara nonce saat start liveness, instance quality hint yang tidak dipakai, handler OCR manual yang sudah tidak memiliki tombol, serta import controller yang tidak terpakai. Pengambilan otomatis tetap memakai receipt server; pemilik sesi, CAPTCHA, nonce, replay, masa berlaku, kualitas capture, kontrol wajib dan routing demo tetap diperiksa. Model/bobot dan angka kalibrasi tidak diubah. Tidak ada data pemohon yang dihapus oleh pekerjaan audit ini.

Tes regresi mereproduksi kegagalan sebelum perbaikan, lalu menguji recovery setelah cancellation, slot penuh, frame retry, capture revision baru, navigasi/akun berubah, start ganda dan detail HTTP yang rusak. Hasil suite final tercatat di [TESTING.md](TESTING.md).

Audit ini bukan sertifikasi keamanan atau kalibrasi biometrik. Tidak dilakukan uji webcam pribadi, penilaian akurasi model baru, atau uji beban layanan deployment nyata. CUDA/PostgreSQL tidak tersedia pada lingkungan uji; adaptor remote/S3/Redis hanya diuji lewat fixture yang sudah ada. Penghapusan objek S3 dan transaksi database belum merupakan satu transaksi atomik; deployment remote perlu menguji kegagalan parsial sebelum digunakan. Tidak ditambahkan redesign penyimpanan terdistribusi atau perubahan model untuk menutupi batas tersebut.
