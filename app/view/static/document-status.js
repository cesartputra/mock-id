"use strict";
function documentStatusView(progress, { escape, icon, formatTime }) {
  if (!progress?.stages?.length) return "";
  const labels = { done: "Sudah selesai", current: "Sedang diproses", pending: "Belum dikerjakan", attention: "Perlu tindak lanjut", failed: "Belum disetujui" };
  const symbols = { received: "file", review: "review", complete: "download" };
  return `<section class="document-status-card" aria-labelledby="document-status-title"><h2 id="document-status-title">Status proses dokumen Anda</h2><p class="document-status-intro">Pantau tahapan permohonan iDeb pada server lokal.</p><ol class="document-timeline">${progress.stages.map((stage, index) => {
    const status = Object.hasOwn(labels, stage.status) ? stage.status : "pending";
    return `<li class="document-stage ${status}" ${["current", "attention", "failed"].includes(status) ? 'aria-current="step"' : ""}><span class="document-stage-number">Proses ${index + 1}</span><div class="document-stage-ring">${status === "done" ? icon("check") : status === "failed" ? '<span aria-hidden="true">×</span>' : icon(symbols[stage.key] || "file")}</div><span class="document-stage-state">${labels[status]}</span><h3>${escape(stage.label)}</h3><p>${escape(stage.message)}</p>${stage.at ? `<time datetime="${escape(stage.at)}">${escape(formatTime(stage.at))}</time>` : ""}</li>`;
  }).join("")}</ol><div class="document-status-legend" aria-label="Legenda status"><span class="done">Selesai</span><span class="current">Sedang diproses</span><span class="pending">Belum dikerjakan</span><span class="attention">Perlu tindak lanjut</span><span class="failed">Belum disetujui</span></div><p class="document-status-updated">Pembaruan server: ${escape(formatTime(progress.updated))}${Number.isInteger(progress.revision) ? ` · bukti versi ${progress.revision}` : ""}</p></section>`;
}
if (typeof module !== "undefined") module.exports = { documentStatusView };
