# Pengelolaan data operator — 3.5.0

Pemohon tetap tanpa login. Workspace petugas tetap memakai login dan otorisasi admin/helpdesk; menempatkan menu di navbar tidak membuka akses operator untuk pemohon.

## Clean data satu permohonan

Administrator membuka Data pemohon, memilih nomor permohonan, lalu Clean data. Dialog memperoleh jumlah data dari server dan mengikat konfirmasi pada ID, versi capture dan waktu perubahan terakhir. Pilihan awal adalah foto saja. Checkbox konfirmasi wajib sebelum permintaan dijalankan.

| Pilihan | Dihapus dari server | Dipertahankan |
| --- | --- | --- |
| Foto saja | Foto KTP asli/crop, selfie, foto KYC dan frame gerakan dari semua revisi; array/proof sesi kamera terkait | Identitas JSON, hasil/skor asli, pendaftaran, keputusan, kasus manual dan laporan sintetis |
| Seluruh data permohonan | Semua bukti/revisi, identitas, hasil verifikasi, pendaftaran terkait, issuance/laporan, kasus/jadwal, respons idempotency dan audit yang terkait permohonan | Akun login, permohonan lain termasuk NIK sama, kunci/model/konfigurasi, satu catatan administratif penghapusan tanpa ID/nama/NIK pemohon |

Satu permohonan berarti satu `APP-…`, bukan seluruh data pengguna/NIK/browser. Hapus foto saja tidak mengarang skor baru atau membatalkan laporan yang sudah sah; review yang masih membutuhkan foto harus meminta capture baru. Foto yang dihapus tidak dimuat kembali oleh galeri. Penghapusan penuh menghilangkan permohonan dari lookup dan melepas kapasitas kasus manualnya.

Penghapusan ditolak jika versi/waktu perubahan tidak sesuai atau capture/PDF masih diproses. Invalidation sesi dan transaksi database mencegah respons lama menyimpan ulang foto. OCR crop yang berjalan ketika cleanup terjadi harus memvalidasi kembali source dan retensinya sebelum menyimpan.

Penghapusan ini menghapus data aktif pada database/storage aplikasi. Ia tidak menghapus file PDF/foto yang sudah disalin atau diunduh ke perangkat, snapshot volume, backup terpisah, atau menjamin forensik media fisik. Penyimpanan lokal menggunakan transaksi dan `secure_delete` SQLite. Jika adapter storage privat dipakai, objek terenkripsi juga diminta dihapus; gangguan storage tidak dilaporkan sebagai penghapusan berhasil dan perlu ditangani sebelum retry. Tidak ada adapter storage eksternal baru yang diaktifkan.

## Foto asli dan crop KTP

Foto asli adalah frame yang diterima/decoded server sesuai batas resolusi aplikasi, dibersihkan EXIF dan disimpan sebagai JPEG 90. Crop merupakan turunan tambahan dari gambar yang sama: area geometris yang dipilih proses OCR, koreksi perspektif, tanpa upscale, binding app/subject/revision dan retensi yang sama. Metadata menyimpan `derived_from` dan koordinat area sumber. Crop menambah bukti visual, tidak mengganti identitas atau keputusan.

Jika OCR memakai full-frame karena bingkai belum ditemukan, aplikasi tidak menamai seluruh latar sebagai crop kartu. Operator dapat mencoba pembuatan crop dari foto tersimpan. Server membaca ulang dengan OCR lokal, memerlukan NIK sama dengan identitas server, lalu menyimpan satu crop per versi secara idempoten. Foto yang dihapus/retensinya habis atau diganti saat OCR tidak dapat disimpan kembali melalui endpoint ini. Ketika area masih belum dapat dipisahkan, UI meminta capture baru dengan bingkai terlihat dan mempertahankan foto asli.

## Endpoint

| Endpoint | Akses | Perilaku |
| --- | --- | --- |
| `GET /api/operator/applications/{id}/cleanup` | Admin | Rencana/jumlah data dan snapshot versi untuk konfirmasi |
| `POST /api/operator/applications/{id}/cleanup` | Admin | Body `mode: photos/full`, `capture_revision`, `expected_updated_at`, `confirm_application_id`; cakupan satu APP |
| `POST /api/applications/{id}/document-crop` | Admin / helpdesk berwenang | Crop OCR dari foto KTP tersimpan pada versi aktif |
| `GET /api/evidence/{id}` | Sesuai ownership/otorisasi bukti | Foto/crop terenkripsi, respons `no-store`; foto terhapus menghasilkan 410 |

Origin dan `X-Local-Client` tetap wajib untuk mutasi. Pemohon/helpdesk tidak dapat memakai endpoint cleanup; helpdesk tidak mendapat akses aplikasi lain hanya karena mengetahui nomor APP.
