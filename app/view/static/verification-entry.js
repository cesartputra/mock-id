"use strict";

// The image and answer are generated locally; only the server grants a receipt.
class VerificationEntryGate {
  constructor({ api, showDialog, getDialog, escape }) {
    Object.assign(this, { api, showDialog, getDialog, escape });
    this.pending = null;
    this.generation = 0;
    this.verifyTimer = null;
  }

  open() {
    if (this.pending) return Promise.resolve(null);
    return new Promise((resolve) => {
      this.pending = { resolve, challenge: null, receipt: null, loading: false, solving: false,
        dragging: false, lastCheckedOffset: null, step: "consent", consent: false };
      this.showConsent();
      this.dialog = this.getDialog();
      this.onInput = (event) => {
        if (!this.pending) return;
        if (event.target.id === "entry-puzzle-slider") {
          this.movePiece();
          if (!this.pending?.dragging) this.scheduleCheck();
        }
        if (event.target.id === "verification-consent") {
          this.pending.consent = event.target.checked;
          this.update();
        }
      };
      this.onClick = (event) => {
        const button = event.target.closest("button");
        if (!button || button.disabled) return;
        if (button.hasAttribute("data-entry-consent-next")) this.acknowledge();
        if (button.hasAttribute("data-entry-back")) this.back();
        if (button.hasAttribute("data-entry-reload")) this.loadPuzzle();
        if (button.hasAttribute("data-entry-cancel")) this.cancel();
      };
      this.onClose = () => { if (!this.dialog.open) this.finish(null); };
      this.onPointerDown = (event) => {
        if (event.target.id !== "entry-puzzle-slider" || !this.pending) return;
        this.pending.dragging = true;
        clearTimeout(this.verifyTimer);
      };
      this.onPointerUp = () => {
        if (!this.pending?.dragging) return;
        this.pending.dragging = false;
        this.scheduleCheck(250);
      };
      this.onPointerCancel = () => {
        if (this.pending) this.pending.dragging = false;
        clearTimeout(this.verifyTimer);
      };
      this.pointerTarget = typeof window !== "undefined" ? window : this.dialog;
      this.dialog.addEventListener("input", this.onInput);
      this.dialog.addEventListener("change", this.onInput);
      this.dialog.addEventListener("click", this.onClick);
      this.dialog.addEventListener("close", this.onClose);
      this.dialog.addEventListener("pointerdown", this.onPointerDown);
      this.pointerTarget.addEventListener("pointerup", this.onPointerUp);
      this.pointerTarget.addEventListener("pointercancel", this.onPointerCancel);
      this.update();
    });
  }

  showConsent() {
    this.showDialog("Pernyataan dan persetujuan", `
      <div class="verification-entry entry-consent-step">
        <div class="entry-body">
          <ol class="entry-statements">
            <li>Aplikasi ini merupakan <strong>demo integrasi lokal</strong> dan tidak mengirim permohonan ke OJK.</li>
            <li><strong>Saya meminta informasi untuk diri sendiri</strong> dan menggunakan KTP milik saya.</li>
            <li><strong>Saya setuju memproses capture pada server lokal ini.</strong> Foto KTP, liveness, dan foto diri bersama KTP digunakan untuk pemeriksaan identitas.</li>
            <li>Bukti yang diperlukan disimpan <strong>terenkripsi sesuai retensi demo</strong> untuk pemeriksaan manual oleh petugas yang berwenang.</li>
            <li>Jika bukti belum cukup, saya dapat diminta mengambil ulang tahap terkait atau mengikuti pemeriksaan manual.</li>
            <li>Dukcapil dianggap lolos simulasi. PDF berisi identitas dari KTP dan data keuangan sintetis; <strong>bukan laporan SLIK resmi</strong>.</li>
          </ol>
          <label class="entry-consent" for="verification-consent">
            <input type="checkbox" id="verification-consent" ${this.pending.consent ? "checked" : ""}>
            <span>Saya menyatakan telah membaca, memahami, dan menyetujui seluruh pernyataan ini.</span>
          </label>
        </div>
        <div class="form-actions entry-consent-actions"><button type="button" class="button" data-entry-cancel>Kembali</button>
          <button type="button" class="button primary" id="entry-consent-next" data-entry-consent-next disabled>Saya Mengerti</button>
        </div>
      </div>`);
  }
  acknowledge() {
    const state = this.pending;
    if (!state || state.step !== "consent" || !this.node("#verification-consent").checked) return;
    state.consent = true; state.step = "captcha";
    this.showDialog("Verifikasi keamanan", `
      <div class="verification-entry">
        <div class="entry-body">
          <p>Pernyataan telah disetujui. Selesaikan puzzle untuk melanjutkan ke verifikasi identitas.</p>
          <section class="entry-captcha" aria-labelledby="entry-captcha-title">
            <div class="entry-captcha-heading"><h3 id="entry-captcha-title">Selesaikan puzzle</h3>
              <button type="button" class="button link" id="entry-puzzle-reload" data-entry-reload>Ganti puzzle</button>
            </div>
            <p id="entry-puzzle-help">Geser potongan ke lubang yang sesuai. Puzzle diperiksa otomatis saat slider dilepas atau berhenti digeser. Jika salah, slider kembali ke awal dan puzzle berganti. Jika benar, verifikasi dimulai otomatis. Tombol panah pada keyboard juga dapat digunakan.</p>
            <div id="entry-puzzle"></div>
            <p id="entry-puzzle-status" class="entry-puzzle-status" role="status" aria-live="polite"></p>
          </section>
          <p class="text-error" id="entry-error" role="alert"></p>
        </div>
        <div class="form-actions"><button type="button" class="button" data-entry-back>Kembali</button>
          <span class="micro">Lanjut otomatis setelah puzzle sesuai.</span>
        </div>
      </div>`);
    this.loadPuzzle();
  }
  back() {
    const state = this.pending;
    if (!state) return;
    this.generation++; clearTimeout(this.verifyTimer);
    Object.assign(state, { step: "consent", receipt: null, challenge: null,
      loading: false, solving: false, dragging: false, lastCheckedOffset: null });
    this.showConsent(); this.update();
  }
  node(selector) { return this.dialog.querySelector(selector); }
  message(text, error = false) {
    this.node(error ? "#entry-error" : "#entry-puzzle-status").textContent = text;
  }
  update() {
    const state = this.pending;
    if (!state) return;
    if (state.step === "consent") {
      this.node("#entry-consent-next").disabled = !this.node("#verification-consent").checked;
      return;
    }
    this.node("#entry-puzzle-reload").disabled = state.loading || state.solving;
    const slider = this.node("#entry-puzzle-slider");
    if (slider) slider.disabled = state.loading || state.solving || !state.challenge || !!state.receipt;
  }
  movePiece() {
    const state = this.pending;
    if (!state?.challenge) return;
    const offset = Number(this.node("#entry-puzzle-slider").value);
    this.node("#entry-puzzle-piece").style.left = `${100 * offset / state.challenge.width}%`;
  }
  scheduleCheck(delay = 500) {
    clearTimeout(this.verifyTimer);
    const state = this.pending;
    if (!state?.challenge || state.dragging || state.loading || state.solving || state.receipt) return;
    this.verifyTimer = setTimeout(() => {
      if (this.pending !== state || state.dragging) return;
      const offset = Number(this.node("#entry-puzzle-slider").value);
      if (offset !== state.lastCheckedOffset) this.solve();
    }, delay);
  }
  async loadPuzzle(notice = "") {
    const state = this.pending;
    if (!state || state.step !== "captcha" || state.loading || state.solving) return;
    clearTimeout(this.verifyTimer);
    const generation = ++this.generation;
    state.loading = true; state.receipt = null; state.challenge = null;
    state.dragging = false; state.lastCheckedOffset = null;
    this.node("#entry-puzzle").innerHTML = '<p>Menyiapkan puzzle…</p>';
    this.message(""); this.message(notice, true); this.update();
    try {
      const c = await this.api("/verification-entry/challenge", { method: "POST" });
      if (this.pending !== state || generation !== this.generation) return;
      state.challenge = c;
      this.node("#entry-puzzle").innerHTML = `
        <div class="entry-puzzle-image" style="aspect-ratio:${c.width}/${c.height}">
          <img src="${this.escape(c.background)}" alt="Gambar puzzle dengan lubang untuk potongan">
          <img id="entry-puzzle-piece" class="entry-puzzle-piece" src="${this.escape(c.piece)}" alt="Potongan puzzle yang digeser"
            style="width:${100*c.piece_size/c.width}%;top:${100*c.piece_y/c.height}%;left:0">
        </div>
        <label class="entry-slider-label" for="entry-puzzle-slider">Geser untuk menyusun puzzle</label>
        <input type="range" id="entry-puzzle-slider" min="0" max="${c.max_offset}" step="1" value="0" aria-describedby="entry-puzzle-help">`;
      this.node("#entry-puzzle-slider").value = "0";
      this.movePiece();
      this.message("Puzzle siap. Geser potongan; pemeriksaan berjalan otomatis.");
    } catch (error) {
      if (this.pending === state && generation === this.generation) this.message(error.message, true);
    } finally {
      if (this.pending === state && generation === this.generation) { state.loading = false; this.update(); }
    }
  }
  async solve() {
    const state = this.pending;
    if (!state?.challenge || state.loading || state.solving || state.receipt) return;
    const generation = this.generation;
    clearTimeout(this.verifyTimer);
    state.lastCheckedOffset = Number(this.node("#entry-puzzle-slider").value);
    state.solving = true; this.message("Memeriksa puzzle…"); this.message("", true); this.update();
    try {
      const receipt = await this.api("/verification-entry/solve", { method: "POST", body: JSON.stringify({
        challenge_id: state.challenge.challenge_id,
        offset: state.lastCheckedOffset,
      }) });
      if (this.pending !== state || generation !== this.generation) return;
      if (!receipt.captcha_token || typeof receipt.captcha_token !== "string" || !(receipt.expires_in > 0))
        throw new Error("Respons CAPTCHA belum sah. Ganti puzzle dan coba kembali.");
      state.receipt = receipt.captcha_token;
      state.solving = false;
      this.message("Puzzle sesuai. Memulai verifikasi identitas…");
      this.continue();
    } catch (error) {
      if (this.pending !== state || generation !== this.generation) return;
      if (error.status === 422 || error.status === 409) {
        state.solving = false;
        await this.loadPuzzle(error.status === 422
          ? "Posisi potongan belum sesuai. Slider direset dan puzzle baru disiapkan."
          : "Puzzle sudah tidak berlaku. Slider direset dan puzzle baru disiapkan.");
      } else {
        this.message(error.message, true); this.message("Pemeriksaan belum selesai. Coba lagi atau ganti puzzle.");
      }
    } finally {
      if (this.pending === state && generation === this.generation) { state.solving = false; this.update(); }
    }
  }
  continue() {
    const state = this.pending;
    if (!state?.receipt || state.step !== "captcha" || state.loading || state.solving || !state.consent) return;
    this.finish({ consent: true, captcha_token: state.receipt });
    this.dialog.close();
  }
  cancel() { if (this.pending) { this.finish(null); this.dialog.close(); } }
  finish(value) {
    const state = this.pending;
    if (!state) return;
    this.pending = null; this.generation++; clearTimeout(this.verifyTimer);
    this.dialog.removeEventListener("input", this.onInput);
    this.dialog.removeEventListener("change", this.onInput);
    this.dialog.removeEventListener("click", this.onClick);
    this.dialog.removeEventListener("close", this.onClose);
    this.dialog.removeEventListener("pointerdown", this.onPointerDown);
    this.pointerTarget.removeEventListener("pointerup", this.onPointerUp);
    this.pointerTarget.removeEventListener("pointercancel", this.onPointerCancel);
    state.resolve(value);
  }
}

if (typeof module !== "undefined") module.exports = { VerificationEntryGate };
