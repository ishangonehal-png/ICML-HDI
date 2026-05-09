from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = REPO_ROOT / "scripts" / "ci" / "check_data_contract_tooling.py"


def _load_check_module():
    spec = importlib.util.spec_from_file_location("_ci_check_data_contract_tooling", CHECK_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_check() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_data_contract_tooling_script_passes() -> None:
    result = _run_check()

    assert result.returncode == 0, (
        "Data-contract tooling check failed.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


def test_data_contract_tooling_reports_mvp50_guardrail_markers() -> None:
    result = _run_check()

    assert result.returncode == 0, (
        "Data-contract tooling check failed before marker validation.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )

    expected_markers = [
        "Data-contract core + MVP50 module files exist",
        "Core cohort/download scripts are callable and syntax-valid",
        "MVP50 detachable module entrypoints are callable",
        "Dataset constants and wrapper delegation contracts are intact",
        "MVP50 module public symbol contracts are intact",
    ]

    missing = [marker for marker in expected_markers if marker not in result.stdout]
    assert not missing, (
        "Data-contract tooling output is missing expected MVP50 guardrail markers:\n- "
        + "\n- ".join(missing)
        + f"\n\nSTDOUT:\n{result.stdout}"
    )


def test_data_contract_tooling_runner_uses_isolated_process_session(monkeypatch) -> None:
    module = _load_check_module()
    captured_kwargs: dict[str, object] = {}
    captured_timeout: list[int | None] = []

    class _FakeProcess:
        pid = 12345
        returncode = 0

        def communicate(self, timeout=None):
            captured_timeout.append(timeout)
            return ("ok", "")

        def poll(self):
            return self.returncode

    def _fake_popen(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return _FakeProcess()

    monkeypatch.setattr(module.subprocess, "Popen", _fake_popen)

    result = module._run([sys.executable, "--version"], timeout_seconds=17)
    assert result.returncode == 0
    assert captured_kwargs.get("start_new_session") is True
    assert captured_timeout == [17]


def test_data_contract_tooling_runner_terminates_timed_out_process_group(monkeypatch) -> None:
    module = _load_check_module()
    kill_signals: list[tuple[int, int]] = []

    class _TimeoutProcess:
        pid = 24680
        returncode = 0

        def communicate(self, timeout=None):
            raise module.subprocess.TimeoutExpired(cmd=["fake"], timeout=timeout)

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            raise AssertionError("terminate should not be used when killpg is available")

        def kill(self):
            raise AssertionError("kill should not be used when killpg is available")

    def _fake_popen(*args, **kwargs):
        return _TimeoutProcess()

    monkeypatch.setattr(module.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(
        module.os,
        "killpg",
        lambda pid, sig: kill_signals.append((pid, sig)),
        raising=False,
    )

    result = None
    try:
        module._run([sys.executable, "--version"], timeout_seconds=3)
    except RuntimeError as exc:
        result = str(exc)

    assert result is not None
    assert "Command timed out after 3s" in result
    assert kill_signals == [(24680, module.signal.SIGTERM)]
