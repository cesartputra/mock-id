# Kebijakan routing yang dapat diperiksa

`ScorePolicy`/`ScoreCalibrator` terpisah dari runtime model dan state permohonan. `demo_routing_score` 0–100, `calibrated=false`, versi `demo-routing-v3-arcface-r50`. Semua input berasal dari inference sebenarnya; fixture hanya dipakai tes/QA terpisah. Metrik mentah tidak diubah menjadi persentase kepastian identitas dan tidak dirata-ratakan langsung.

## Pemetaan demo

Interpolasi linear antar titik, clamp di ujung. `face` memakai minimum cosine KTP↔selfie dan selfie↔foto KYC, kemudian dipetakan:

| Komponen | Titik (nilai model → nilai routing) | Bobot |
|---|---|---|
| Face | -1→0; .2→40; .4→75; .5→92; .6→97; .85→100 | .45 |
| PAD | 0→0; .8→75; .9→92; .95→97; .995→100 | .35 |
| OCR | 0→0; .6→60; .8→85; .9→95; 1→100 | .20 |

`score = clamp(.45*mapped_face + .35*mapped_pad + .20*mapped_ocr, 0,100)`. OCR confidence aggregate bukan keyakinan tiap digit NIK; kecocokan NIK kedua foto adalah kontrol terpisah. PAD memakai nilai minimum yang diperiksa rangkaian model. Pemetaan/bobot **heuristik**, belum memiliki bukti statistik bahwa skor 95 atau 75 berhubungan dengan risiko populasi tertentu. Cosine mentah, OCR, PAD tidak dibulatkan sebelum scoring/keputusan. UI memotong tampilan dua desimal agar 94,999 tidak tampak 95 meskipun keputusan memakai nilai asli.

Urutan: capture bermasalah → CAPTURE_RETRY; error/model tidak tersedia/metrik hilang → TECHNICAL_PENDING (score null bila input tidak memadai); aturan PAD ketat → REJECTED/security_review. Pengecualian demo tanpa kalibrasi disetujui: bukti gerakan/nonce dan identitas lengkap dengan PAD meragukan → MANUAL_PENDING, termasuk bila skor di bawah 75. Nilai PAD mentah dan kontrol wajib yang gagal tetap disimpan; tidak ada persetujuan otomatis/PDF sebelum review. Kualitas/penutup wajah atau gerakan yang gagal tetap CAPTURE_RETRY. Produksi/profil terkalibrasi tidak memakai pengecualian ini. Tidak ada penggantian metrik kosong dengan nol. Untuk hasil yang dapat dinilai: <75 REJECTED; ≥75 dan <95 MANUAL_PENDING; ≥95 AUTO_APPROVED **hanya** jika setiap pemeriksaan wajib terpenuhi dan profil mengizinkannya. ≥95 dengan syarat gagal → MANUAL_PENDING atau status capture/teknis yang sesuai, tanpa penerbitan.

Pemeriksaan wajib: nonce/proof/selfie/revision yang sudah divalidasi server; dokumen/NIK/nama/tanggal lahir lengkap dan sesuai; kontrol wajah, tangan, visibilitas, kontinuitas, gerakan dan PAD; tidak ada aturan penolakan keamanan; kewenangan pemohon; prosedur validasi identitas disetujui. Demo memakai local capture + kapabilitas browser/pernyataan diri sendiri sebagai prosedur **synthetic_only**, tidak membuktikan kewenangan atau identitas resmi. Produksi membutuhkan adapter identitas dan binding kewenangan pemohon ke subjek dari aplikasi induk; checkbox petugas tidak menciptakan validasi resmi.

ViT Real/Fake tetap diagnostik, tidak masuk skor, kontrol wajib atau penolakan. GPU/CoreML dan gerakan bukan jaminan deteksi semua replay, deepfake/injection. ArcFace/PAD belum dikalibrasi untuk perubahan wajah sepuluh tahun, semua kamera/populasi, atau threshold operasional.

## Menuju kalibrasi produksi

[Template](../config/calibration-template.json) sengaja **tidak disetujui** dan tidak dapat mengaktifkan kalibrasi. Artefak diperiksa untuk SHA-256 yang dipin di konfigurasi aman, schema=1, face_model=insightface-buffalo-l-w600k-r50, version, approved_by, evaluation_report, titik monotonic/finite 0–100 dan bobot positif berjumlah satu. File/version/SHA adalah artefak yang dapat diaudit; kode tidak menganggap laporan evaluasi benar hanya karena string diisi. Organisasi pemilik wajib memeriksa dataset berlabel, pemisahan training/evaluasi, kamera, variasi usia/kualitas, kesalahan menerima/menolak, attack evaluation dan ambang yang sesuai sebelum mem-pin artefak tersebut.

Konfigurasi `MOCK_ID_CALIBRATION_FILE` dan `MOCK_ID_CALIBRATION_SHA256` hanya lewat backend, tidak browser. Tanpa artefak disetujui, persetujuan otomatis produksi diblokir. Tanpa identity/authority adapter berwenang, penerbitan produksi tetap ditahan **walaupun calibrated=true dan score=100**. Keputusan dan evidence menyimpan policy version serta snapshot aturan model; perubahan bukti membatalkan keputusan lama. Tidak ada akurasi KYC atau ketahanan serangan yang dibuktikan oleh tes fixture.

Pada 3.1.0 ruang embedding berubah dari SFace ke ArcFace R50. Ambang lama tidak digunakan sebagai hasil kalibrasi; konfigurasi legacy memakai nilai demo 0.40. Artefak kalibrasi untuk model lain atau tanpa `face_model` ditolak. Versi kebijakan baru tidak mengubah keputusan historis yang sudah disimpan. Kemiripan fixture buram/downsample bukan evaluasi perubahan usia atau akurasi KTP nyata.
