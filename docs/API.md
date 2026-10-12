# Kontrak API demo / integrasi induk

OpenAPI aktual: `/openapi.json`, Swagger `/docs`. MVC: `app/model`, `app/view`, `app/controller`, `app/services`. Semua `/api/*` memerlukan cookie kapabilitas HttpOnly `mock_id_guest` untuk pemohon, `mock_id_session` untuk petugas, atau bearer opaque session; login/signup/guest pengecualian. `POST /auth/guest` otomatis membuat/memulihkan principal browser tanpa password. `X-Workspace-Mode: public|operator` memilih cookie; bearer tetap mempunyai prioritas. Tidak ada login pemohon pada UI. **`X-Local-Client: mock-id` hanya marker origin/CSRF**, diwajibkan untuk perubahan, bukan autentikasi. Semua request produksi harus HTTPS. Endpoint browser same-origin: widget ditempel lewat reverse proxy origin aplikasi induk, bukan public iframe dengan credential/token pada URL.

## Peran dan endpoint

| Endpoint | Peran / tujuan |
|---|---|
| POST `/auth/signup`, `/auth/login` | Signup hanya pemohon demo; role tidak boleh dipilih browser. Login cookie; akun integration mendapat bearer untuk backend. |
| POST `/auth/guest` | Bootstrap browser pemohon tanpa login; cookie HttpOnly/SameSite Strict 30 hari; akses lintas pemilik tetap ditolak. |
| GET `/auth/me`, POST `/auth/logout` | Akun aktif dan pencabutan sesi login |
| POST `/sessions` `{application_id?: string}` | Pemohon / admin demo untuk akun sendiri. Membuat permohonan baru atau sesi baru dengan invalidasi revision lama. |
| POST `/applications/{id}/attest` `{accepted: bool}` | Pemilik menyatakan permohonan untuk diri sendiri sebelum keputusan |
| `/sessions/{id}/document`, `/identity`, `/capture-check`, `/auto-capture/check`, `/liveness/*`, `/verify`, `/retake`, `/retry` | Nonce, proof, selfie hash, capture revision dan limits lama tetap diperiksa. `X-Capture-Revision` direkomendasikan/wajib pada widget baru. Sesi milik akun lain ditolak. |
| GET `/applications`, `/applications/{id}` | Pemohon: milik sendiri. Helpdesk: kasus belum diambil atau ditugaskan kepadanya. Admin: metadata/operasional. |
| GET `/manual/calendar` | Kalender kapasitas Jakarta, working_day/used/remaining/available; tidak menjanjikan slot. |
| POST `/applications/{id}/manual/try-today` | Coba kuota hari ini tanpa capture baru; transaksi/idempotensi harian internal, `manual_admission` menyatakan RESERVED/CAPACITY_FULL/OUTSIDE_HOURS. Dipanggil otomatis setelah keputusan manual. |
| POST `/applications/{id}/manual/reserve` atau `/move` `{day:"YYYY-MM-DD"}` | Klien akun legacy; `Idempotency-Key` 8–100 karakter. Browser guest hanya reserve hari ini dan move ditolak. Validasi horizon, hari/jam, retensi, kapasitas dan kasus unik atomik. |
| POST `/applications/{id}/manual/cancel` | Pemilik; idempotency key; kapasitas kembali jika belum mulai pemeriksaan |
| POST `/applications/{id}/manual/start` | Helpdesk; atomik menugaskan kasus kepada actor pada jadwal dan jam layanan |
| POST `/applications/{id}/manual/review` | Helpdesk yang ditugaskan; body di bawah; revision harus tepat |
| GET `/evidence/{id}` | Cookie/bearer, otorisasi pemilik/kasus, revision aktif, expiry, audit/no-store. Pemohon tidak memperoleh hasil model mentah/diagnostik. |
| POST `/applications/{id}/slik`, GET endpoint sama | Pemilik: request/retry issuance dan baca laporan; stable issuance ID terikat keputusan/revision |
| POST `/registrations`, GET `/registrations/{id}` | Receipt mock lokal, milik sendiri. Perseorangan memerlukan keputusan persisten, canonical name/verification ID, bukan sesi aktif. Bukan penerbitan SLIK. Profil produksi menahan adapter receipt demo. |
| GET `/workspace`, GET `/operator/metrics` | Workspace operator (helpdesk terfilter kasus), metrics admin; bukan public dataset |
| PUT `/settings`, GET/PUT `/policy/capacity` | Admin; audit. Contoh kapasitas di config/capacity-demo.json |

Capture memakai FormData seperti API existing, dengan nonce/proof server. Respons final menambah `application` (state persisten, routing, revisi, instruksi). Metrik model raw/diagnostik hanya untuk operator; pemohon mendapat progress, kontrol, pesan dan skor routing dengan keterbatasannya. Check kualitas client tidak pernah mengubah keputusan server.

Review:

```json
{
  "decision": "approve",
  "capture_revision": 2,
  "note": "Dasar pemeriksaan dokumen dan kewenangan pemohon.",
  "identity_review": true,
  "authority_review": true
}
```

Keputusan `approve|reject|repair`. Checkbox adalah dasar review lokal, **bukan** bukti Dukcapil resmi. Server menahan persetujuan produksi ketika authority/identity/control wajib belum terpenuhi. Audit menyimpan actor/action/revision tanpa note/NIK/token/gambar; note tersegel di EvidenceStore.

Snapshot contoh struktur (nilai routing berasal dari model, tidak boleh dikirim browser):

```json
{
  "id": "APP-opaque-id",
  "state": "MANUAL_PENDING",
  "capture_revision": 2,
  "routing": {
    "demo_routing_score": null,
    "routing_score": null,
    "calibrated": false,
    "policy_version": "demo-routing-v1",
    "scope": "synthetic_only"
  },
  "identity_verified": false,
  "channel": "authenticated_dashboard"
}
```

Contoh di atas **schema**, bukan skor/preset aplikasi. Field score null bila tidak dapat dinilai. Routing 74,99/75/94,99/95 diperiksa sebelum pembulatan.

## Backend induk / widget

1. Host mengautentikasi pemohon dan memetakan principal host ke principal pemohon modul (kapabilitas browser demo; prosedur/kanal yang diverifikasi produksi menjadi kewenangan host). Widget baru berjalan same-origin melalui proxy; token layanan integration tidak pernah dimasukkan ke browser.
2. Buat permohonan/capture, simpan `application_id` dan revision server. Widget mengirim gambar/gerakan, bukan skor/keputusan. Bila timeout, cek status dan jangan membuat permohonan atau slot ganda.
3. Host backend menggunakan akun role **integration** yang dibuat di luar browser. Baca GET `/integration/applications/{id}/decision?owner_id=principal-module-id`. Respons: canonical `subject_id` HMAC, owner, revision, keputusan, expiry, scope dan identity_verified. Mapping owner harus berasal dari sesi host yang berwenang, bukan field browser. Mengetahui application ID sendiri tidak mengotorisasi pemohon lain.
4. POST `/integration/handoff` dengan bearer integration + marker:

```json
{
  "application_id": "APP-opaque-id",
  "owner_id": "principal-module-id",
  "subject_id": "64-hex-HMAC-from-authorized-server-decision"
}
```

Server membandingkan owner/subjek dengan keputusan persisten dan membuka identitas dari EvidenceStore. Nama/NIK browser tidak dipakai untuk downstream. Akun integration adalah layanan dipercaya untuk backend induk, bukan delegasi user serba boleh; batasi akses network/IAM dan mapping scope di host.

5. SlikServiceAdapter `fetch(identity, idempotency_key)` menerima identitas server dan stable issuance ID. Adapter resmi harus memakai API yang diotorisasi, deadline/lease dan idempotensi; **tidak ada direct query database SLIK oleh model/worker**. Factory production default menahan layanan resmi yang belum dikonfigurasi. Adapter identity `IdentityValidationAdapter.check(identity)` serta `RequesterAuthorityAdapter.check(owner, identity, attested)` membutuhkan receipt/prosedur berwenang dari host; boolean browser/review tidak cukup. Demo menggunakan mock dan synthetic_only.
6. Hasil dikembalikan lewat dashboard cookie browser pemilik (demo), atau kanal pemohon yang diverifikasi host (produksi). Untuk email produksi, host harus mengimplementasikan verifikasi kanal dan notification adapter; aplikasi ini tidak mengirim email atau hasil ke email formulir.

Integrasi ini menyediakan kontrak server/widget, **belum** integrasi OJK, IdP, kontrak Dukcapil resmi, atau approval SOP/keamanan produksi.

## Errors dan idempotensi

401 kapabilitas browser/sesi petugas tidak tersedia; 403 role/origin/kanal tidak sah; 404 resource milik akun lain/tidak ada; 409 transisi/revision/keputusan tidak sah atau `detail.code=CAPACITY_FULL`; 410 sesi/bukti/retensi berakhir; 422 input atau jadwal; 429 admission/rate/attempt limits; 503 model/downstream/adapter tidak tersedia. Semua JSON, tidak mem-parsing “Internal Server Error” sebagai JSON. CAPTURE_RETRY/TECHNICAL_PENDING tidak berarti REJECTED atau score=0.

Slot: key tetap saat retry payload sama, key baru untuk tindakan berbeda. Kasus unik per application. Penerbitan: DB unique(application,revision), ID downstream tetap pada retry, lease token menolak hasil attempt lama. Penyedia resmi harus mendukung idempotensi ID tersebut; DB lokal saja tidak dapat menjamin exactly-once pada API eksternal yang tidak punya kontrak idempotensi.

Endpoint legacy `/records/{id}/review|schedule` menolak dengan 409; status approved historis tanpa application/evidence tidak memberi akses hasil. Data SQLite lama dipertahankan, tidak diberi pemilik/otorisasi baru secara otomatis.

Guest capability hanya mengotorisasi kepemilikan resource demo, bukan identitas hukum. Produksi tetap membutuhkan adapter/prosedur identitas, kewenangan dan kanal penerimaan yang disetujui; tidak otomatis sah karena guest cookie tersedia. Cookie tidak pernah dimasukkan URL atau localStorage.
