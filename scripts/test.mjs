import { run, venvPython } from "./python.mjs";
run(venvPython, ["-m", "pytest", "-q", "tests"]);

run(process.execPath, ["--test", "tests/test_capture_feedback.cjs"]);
