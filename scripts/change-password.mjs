import { run, venvPython } from "./python.mjs";
run(venvPython, ["scripts/change_password.py", ...process.argv.slice(2)]);
