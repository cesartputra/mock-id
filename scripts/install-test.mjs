import { run, venvPython } from "./python.mjs";
run(venvPython, ["-m", "pip", "install", "-r", "requirements-dev.txt"]);
