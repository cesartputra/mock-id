import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
export const root = path.resolve(
  fileURLToPath(new URL("../", import.meta.url)),
);
// Parse only plain configuration values; never execute .env as shell code.
const envPath = path.join(root, ".env");
if (fs.existsSync(envPath))
  for (const line of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const match = line.match(/^([A-Z][A-Z0-9_]*)=(.*)$/);
    if (
      match &&
      (match[1].startsWith("MOCK_ID_") ||
        ["PORT", "WORKER_PORT"].includes(match[1])) &&
      process.env[match[1]] === undefined
    ) {
      process.env[match[1]] = match[2].trim().replace(/^(['"])(.*)\1$/, "$2");
    }
  }
export const venvPython = path.join(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
export function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: "inherit",
    env: {
      ...process.env,
      PIP_CACHE_DIR: path.join(root, ".cache", "pip"),
      MPLCONFIGDIR: path.join(root, ".cache", "matplotlib"),
    },
  });
  if (result.error || result.status !== 0) {
    console.error(
      result.error?.message || `Perintah gagal (${result.status}).`,
    );
    process.exit(result.status || 1);
  }
}
