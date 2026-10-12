"use strict";
async function readApiResponse(response) {
  const text = await response.text();
  let body = null;
  try {
    body = JSON.parse(text);
  } catch {
    // Proxies and older servers can send plaintext/HTML error pages. Never
    // display their contents or let a JSON SyntaxError mask the HTTP status.
  }
  const valid = body !== null && typeof body === "object";
  if (response.ok && valid) return body;
  if (response.ok && response.status === 204 && !text) return null;
  const detail = valid
    ? Array.isArray(body.detail)
      ? body.detail
          .map((e) => `${e.loc?.slice(-1)[0] || "Input"}: ${e.msg}`)
          .join("; ")
      : typeof body.detail === "string"
        ? body.detail
        : null
    : null;
  const fallback = response.ok
    ? "Respons server tidak valid. Coba kembali dan periksa log server."
    : response.status >= 500
      ? `Server lokal mengalami gangguan (HTTP ${response.status}). Coba kembali dan periksa log server.`
      : `Permintaan tidak berhasil (HTTP ${response.status}). Periksa input atau muat ulang halaman.`;
  const error = new Error(detail || fallback);
  error.status = response.status;
  error.code = valid ? body.code : "invalid_response";
  error.retry = valid ? body.retry : null;
  if (
    valid &&
    typeof body.request_id === "string" &&
    /^[a-zA-Z0-9-]{1,64}$/.test(body.request_id)
  ) {
    error.requestId = body.request_id;
    error.message += ` Kode error: ${body.request_id}.`;
  }
  throw error;
}
if (typeof module !== "undefined") module.exports = { readApiResponse };
