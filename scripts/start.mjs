import fs from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import { root, venvPython } from "./python.mjs";
if (!fs.existsSync(venvPython)) {
  console.error(
    "Lingkungan Python belum tersedia. Jalankan npm run setup terlebih dahulu.",
  );
  process.exit(1);
}
const port = process.env.PORT || "4173";
if (!/^\d+$/.test(port) || Number(port) < 1024 || Number(port) > 65535) {
  console.error("PORT harus antara 1024 dan 65535.");
  process.exit(1);
}
const child = spawn(
  venvPython,
  [
    "-m",
    "uvicorn",
    "app.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    port,
    "--no-access-log",
  ],
  {
    cwd: root,
    stdio: "inherit",
    env: {
      ...process.env,
      MPLCONFIGDIR: path.join(root, ".cache", "matplotlib"),
    },
  },
);
child.on("error", (e) => {
  console.error(e.message);
  process.exitCode = 1;
});
child.on("exit", (code) => {
  process.exitCode = code || 0;
});
// Ctrl+C reaches the shared foreground process group, including uvicorn.
// Forwarding it a second time interrupts graceful lifespan cleanup.
process.on("SIGINT", () => {});
process.on("SIGTERM", () => child.kill("SIGTERM"));
