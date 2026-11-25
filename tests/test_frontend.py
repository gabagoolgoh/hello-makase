import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_frontend_cases_4_to_11_run_under_pytest() -> None:
    """Run the jsdom-backed client tests for the built UI's interactions."""
    node = shutil.which("node")
    assert node is not None, "node is required to run the front-end tests"
    if not (FRONTEND / "node_modules" / "jsdom").exists():
        npm = shutil.which("npm")
        assert npm is not None, "npm is required to install the front-end tests"
        installed = subprocess.run(
            [npm, "install", "--no-audit", "--no-fund"],
            cwd=FRONTEND,
            text=True,
            capture_output=True,
            timeout=300,
        )
        assert installed.returncode == 0, installed.stdout + installed.stderr

    result = subprocess.run(
        [node, "--test", "test/app.test.mjs"],
        cwd=FRONTEND,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
