import { run, venvPython } from "./python.mjs";
run(venvPython, ["scripts/create_user.py", ...process.argv.slice(2)]);
