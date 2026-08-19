"""Cross-process byte-stability for `sul.report` (PROJECT_SPEC.md §M5 plan,
point 1). `ReportModel` carries no field populated from wall-clock time,
hostname, cwd, absolute path, or `sklearn.__version__`-adjacent runtime
introspection beyond the one deliberately-recorded version string (see
`sul.report.model`'s module docstring) -- this is what makes two renders of
the *same study* comparable at all across two independent process
invocations, not just two calls in one process (a same-process "two renders
of an identical ReportModel are identical" check cannot catch a wall-clock
defect, since the value is already fixed by the time both renders happen;
this replaces that check with the actual subprocess pattern
`test_orchestrator_determinism.py` uses for seed determinism).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "support" / "run_report_script.py"


def _run_report_script(*, pythonhashseed: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = pythonhashseed
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    output: dict[str, str] = json.loads(result.stdout.strip())
    return output


def test_report_files_are_byte_identical_across_process_invocations() -> None:
    first = _run_report_script(pythonhashseed="0")
    second = _run_report_script(pythonhashseed="1")
    assert first["markdown"] == second["markdown"]
    assert first["html"] == second["html"]
