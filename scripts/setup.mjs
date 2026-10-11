import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { root, venvPython, run } from "./python.mjs";
const candidates = process.env.MOCK_ID_PYTHON
  ? [process.env.MOCK_ID_PYTHON]
  : ["python3.12", "python3.11", "python3", "python"];
const python = candidates.find((command) => {
  const r = spawnSync(command, ["--version"], { encoding: "utf8" });
  return r.status === 0 && /Python 3\.(11|12)\./.test(r.stdout + r.stderr);
});
if (!python && !fs.existsSync(venvPython)) {
  console.error(
    "Pasang Python 3.11 atau 3.12 terlebih dahulu. Contoh: MOCK_ID_PYTHON=python3.12 npm run setup",
  );
  process.exit(1);
}
if (!fs.existsSync(venvPython))
  run(python, ["-m", "venv", path.join(root, ".venv")]);
const version = spawnSync(venvPython, ["--version"], { encoding: "utf8" });
if (
  version.status !== 0 ||
  !/Python 3\.(11|12)\./.test(version.stdout + version.stderr)
) {
  console.error(
    "Versi .venv harus Python 3.11 atau 3.12. Buat ulang .venv dengan versi yang sesuai.",
  );
  process.exit(1);
}
run(venvPython, ["-m", "pip", "install", "-r", "requirements.txt"]);
run(venvPython, ["scripts/setup_models.py", "--warmup"]);
console.log("Setup selesai. Jalankan npm start dan buka http://127.0.0.1:4173");
