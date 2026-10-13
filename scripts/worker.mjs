import { run, venvPython } from "./python.mjs";
run(venvPython, [
  "-m",
  "uvicorn",
  "app.worker:app",
  "--host",
  "127.0.0.1",
  "--port",
  process.env.WORKER_PORT || "4181",
  "--no-access-log",
]);
