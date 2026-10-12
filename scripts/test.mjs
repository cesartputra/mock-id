import { run, venvPython } from "./python.mjs";
run(venvPython, ["-m", "pytest", "-q", "tests"]);

run(process.execPath, [
  "--test",
  "tests/test_quality_gate.cjs",
  "tests/test_capture_feedback.cjs",
  "tests/test_capture_state.cjs",
  "tests/test_auto_capture.cjs",
  "tests/test_api_response.cjs",
  "tests/test_result_presentation.cjs",
]);
