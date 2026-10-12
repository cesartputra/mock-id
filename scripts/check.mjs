import { run, venvPython } from "./python.mjs";
run(process.execPath, ["--check", "app/view/static/app.js"]);
run(process.execPath, ["--check", "app/view/static/capture-feedback.js"]);
run(process.execPath, ["--check", "app/view/static/registration.js"]);
run(process.execPath, ["--check", "app/view/static/capture-state.js"]);
run(process.execPath, ["--check", "app/view/static/auto-capture.js"]);
run(venvPython, ["-m", "compileall", "-q", "app", "scripts"]);
