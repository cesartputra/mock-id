import { run, venvPython } from "./python.mjs";
run(venvPython, ["scripts/list_users.py", ...process.argv.slice(2)]);
