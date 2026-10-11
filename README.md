# mock-id — iDeb Verify demo lokal

Prototipe interaktif berbahasa Indonesia berdasarkan percakapan [Rancang Alur Verifikasi Otomatis](https://chatgpt.com/share/6acba866-18b0-83ec-9287-0fb9eabb5b18), ditambah tahap foto diri sambil memegang KTP.

## Menjalankan

Butuh Node.js 18 atau lebih baru. Tidak perlu `npm install`, API key, Python, atau unduhan model.

```sh
git clone https://github.com/cesartputra/mock-id.git
cd mock-id
npm start
```

Buka **http://127.0.0.1:4173** di browser. Tekan Ctrl+C di terminal untuk berhenti. Di macOS, Anda juga dapat menjalankan `Jalankan Demo.command`. Jika terminal menyatakan Node tidak ditemukan, pasang Node.js terlebih dahulu dari sumber resmi.

Untuk mengganti port:

```sh
PORT=4180 npm start
```

Server hanya mendengarkan pada `127.0.0.1`, sehingga tidak dibuka ke jaringan LAN. Setelah server aktif, tidak ada koneksi internet yang diperlukan.

## Memperbarui aplikasi

Jika repo sudah di-clone, jalankan dari folder `mock-id`:

```sh
git pull --ff-only
npm start
```

Hentikan server lama dengan Ctrl+C sebelum menjalankan server lagi, lalu refresh browser. Tidak perlu `npm install` karena aplikasi tidak memiliki dependensi eksternal. Pembaruan source tidak menghapus data demo di browser; gunakan tombol reset dalam aplikasi untuk memuat ulang data contoh bila diperlukan.

`git pull --ff-only` berhenti jika perubahan lokal atau riwayat branch bertentangan, sehingga tidak membuat merge otomatis. Simpan perubahan lokal Anda sebelum melakukan update jika Git melaporkan konflik.

## Yang dapat dicoba

1. Klik **Verifikasi baru** atau **Coba alur pemohon**.
2. Pilih salah satu skenario di panel samping. Pilihan bisa diubah sampai pemrosesan dimulai.
3. Gunakan KTP contoh, unggah gambar, atau buka kamera. Centang pemahaman demo.
4. Tinjau dan koreksi keluaran OCR contoh: NIK 16 digit, nama, tanggal lahir, dan alamat.
5. Selesaikan tiga tantangan liveness dengan tombol simulasi.
6. Ambil/unggah **foto diri sambil memegang KTP**, atau pilih ilustrasi contoh. Pastikan wajah dan KTP tidak saling menutupi.
7. Jalankan pipeline mock dan lihat hasil. Hasil dapat diunduh sebagai JSON.
8. Untuk hasil manual, buka antrean, tentukan jadwal dalam WIB, dan catat alasan keputusan petugas.
9. Buka **Audit aktivitas** untuk riwayat. Antrean dan audit dapat diekspor ke CSV. Dialog ekspor menyediakan isi file untuk disalin jika browser membatasi unduhan.

Kamera hanya diminta ketika pengguna menekan tombol kamera. Pengambilan foto menggunakan kamera perangkat melalui `getUserMedia` dan bekerja pada localhost/browser yang mendukung. Jika izin ditolak atau kamera tidak tersedia, gunakan gambar contoh atau unggahan. Tantangan liveness tetap simulasi meskipun Anda mengambil foto nyata.

## Skenario

| Skenario | Hasil dan tindak lanjut |
| --- | --- |
| Lulus otomatis | Semua kontrol mock terpenuhi, lalu tampilkan langkah pengajuan contoh. |
| Perbaikan capture | Skor kualitas dokumen rendah; ulang capture dengan percobaan terbatas. |
| Gangguan teknis | Adapter identitas timeout; retry terukur, tanpa masuk antrean manual. |
| Identitas belum pasti | Face similarity rendah; masuk antrean manual dan reservasi petugas. |
| Indikasi serangan | Sinyal spoof/deepfake/injection mock; tampilkan tinjauan keamanan. |

Untuk mencoba pemulihan: setelah hasil perbaikan atau gangguan teknis, tekan ulang/retry dan ubah skenario menjadi **Lulus otomatis**. Setiap percobaan dicatat. Ambang face similarity/liveness dan jumlah percobaan dapat diubah melalui **Modul & konfigurasi**. Ambang diterapkan pada saat pemrosesan dan disimpan bersama hasil; perubahan berikutnya tidak mengubah hasil historis.

## Batas demo

- OCR KTP, keterlihatan wajah/KTP dalam foto KYC, pencocokan dokumen, liveness, face matching, deteksi deepfake, injection, dan Dukcapil **semuanya mock**.
- Gambar unggahan atau hasil kamera hanya menjadi pratinjau. Tidak ada model yang menganalisis gambar; skor berasal dari skenario.
- Foto memegang KTP mendukung pemeriksaan penguasaan dokumen fisik, tetapi demo ini **belum membuktikan kepemilikan sah, keaslian dokumen, ataupun identitas**.
- Nama PaddleOCR, YuNet/SFace, MediaPipe, MiniFASNet, dan DeepfakeBench menjelaskan kandidat arsitektur dari referensi GPT. Paket, bobot, dan model tersebut belum dipasang.
- Belum ada FastAPI, integrasi Dukcapil/OJK, login, penyimpanan server, atau pengajuan iDeb asli.
- Durasi dan confidence di dashboard bersifat ilustratif, bukan benchmark model atau bukti akurasi.
- Kontrol sesi 15 menit, nonce sekali pakai, dan batas percobaan hanya berada di JavaScript browser; untuk produksi harus ditegakkan di backend.
- Audit demo bukan audit yang tahan manipulasi.

## Data lokal

Permohonan fiktif, NIK contoh, konfigurasi, jadwal, keputusan, dan audit disimpan di `localStorage` dengan key `ideb-verify-demo-v1`. Gunakan data fiktif saat mencoba. Data berbeda antar browser/port dan bertahan setelah reload.

Gambar dokumen, selfie, dan foto bersama KTP disimpan sementara dalam memori tab, tidak dimasukkan ke localStorage atau file ekspor. Reload memulai sesi capture baru dan menghapus pratinjau gambar. Kamera dihentikan saat foto diambil atau dialog ditutup.

Gunakan **Modul & konfigurasi → Reset data demo** untuk memuat ulang delapan permohonan awal. Proses reset memiliki dialog konfirmasi. Jadwal disimpan dan ditampilkan dalam zona waktu Asia/Jakarta (WIB).

## Struktur

```text
mock-id/
  package.json
  server.mjs                 # HTTP statis lokal, Node tanpa dependensi
  Jalankan Demo.command      # launcher terminal macOS
  public/
    index.html
    style.css                # layout responsif, tanpa font/CDN eksternal
    app.js                   # capture, rules mock, antrean, audit, ekspor
  tests/flow.mjs             # pengujian keputusan dan kontrol sesi mock
  README.md
```

Pengecekan sintaks:

```sh
npm run check
npm test
```

Untuk menjadikannya implementasi nyata, ganti adapter mock dengan backend dan endpoint inference. Validasi identitas/sumber referensi, pengujian PAD/injection, penanganan manual, lisensi bobot/dataset, dan kontrol sesi perlu dirancang serta dievaluasi tersendiri.

## Verifikasi demo

Lima hasil skenario, capture KYC wajib, masa berlaku sesi, nonce sekali pakai, retry, batas percobaan, perubahan status manual, dan aturan historis diperiksa melalui test Node. Alur pemohon, unggahan foto referensi, hasil lulus/manual/capture/timeout/serangan, reservasi WIB, keputusan petugas, audit, filter antrean, dan pratinjau CSV juga diperiksa di browser. Pengambilan gambar dari kamera fisik belum diuji; preview contoh dan unggahan dapat dipakai tanpa kamera. Unduhan blob tidak terkonfirmasi pada browser in-app, sehingga tersedia pratinjau dan salin isi file sebagai alternatif.
