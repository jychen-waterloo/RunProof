from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from runproof import exec, run, step


@step("required_fails", required=True)
def _required_fails() -> None:
    raise RuntimeError("boom")


@step("required_ok", required=True)
def _required_ok() -> str:
    return "ok"


@step("long_output")
def _long_output() -> str:
    return "x" * 5000


def _latest_receipt(out_dir: Path) -> Path:
    runs_dir = out_dir / "runs"
    receipts = sorted(runs_dir.glob("*/receipt.json"), key=lambda p: p.stat().st_mtime)
    assert receipts
    return receipts[-1]


def test_required_step_missing(tmp_path: Path) -> None:
    with run("required-missing", out_dir=str(tmp_path)):
        with pytest.raises(RuntimeError):
            _required_fails()

    receipt = json.loads(_latest_receipt(tmp_path).read_text(encoding="utf-8"))
    assert receipt["status"] == "integrity_failed"


def test_required_step_success(tmp_path: Path) -> None:
    with run("required-success", out_dir=str(tmp_path)):
        _required_ok()

    receipt = json.loads(_latest_receipt(tmp_path).read_text(encoding="utf-8"))
    assert receipt["status"] == "success"


def test_exec_expect_files_recorded(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("hello", encoding="utf-8")

    with run("exec-files", out_dir=str(tmp_path / "out")):
        exec(
            [
                sys.executable,
                "-c",
                "import shutil,sys; shutil.copy2(sys.argv[1], sys.argv[2])",
                str(src),
                str(dst),
            ],
            expect_files=[str(dst), str(tmp_path / "missing.txt")],
        )

    receipt = json.loads(_latest_receipt(tmp_path / "out").read_text(encoding="utf-8"))
    exec_step = next(step for step in receipt["steps"] if step["kind"] == "exec")
    expected = exec_step["evidence"]["expected_files"]
    assert expected[str(dst)]["exists"] is True
    assert expected[str(tmp_path / "missing.txt")]["exists"] is False


def test_truncation(tmp_path: Path) -> None:
    with run("truncate", out_dir=str(tmp_path)):
        _long_output()

    receipt = json.loads(_latest_receipt(tmp_path).read_text(encoding="utf-8"))
    step_record = next(step for step in receipt["steps"] if step["name"] == "long_output")
    assert len(step_record["evidence"]) == 2000
    assert step_record["evidence"].endswith("...")
