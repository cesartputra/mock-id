import { run, venvPython } from "./python.mjs";
run(venvPython, ["-m", "pytest", "-q", "tests"]);
