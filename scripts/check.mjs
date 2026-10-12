import { run, venvPython } from "./python.mjs";
run(process.execPath, ["--check", "app/view/static/app.js"]);
run(process.execPath, ["--check", "app/view/static/capture-feedback.js"]);
run(venvPython, ["-m", "compileall", "-q", "app", "scripts"]);
