import { run, venvPython } from "./python.mjs";
run(process.execPath, ["--check", "app/view/static/app.js"]);
run(venvPython, ["-m", "compileall", "-q", "app", "scripts"]);
