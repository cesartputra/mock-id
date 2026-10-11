import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
export const root = path.resolve(
  fileURLToPath(new URL("../", import.meta.url)),
);
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
