from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from runproof import FileProbe, exec, run, step


@step("required_fails", required=True)
def _required_fails() -> None:
    raise RuntimeError("boom")


@step("required_ok", required=True)
def _required_ok() -> str:
    return "ok"


@step("long_output")
def _long_output() -> str:
    return "x" * 5000


class BrokenProbe:
    name = "broken"
    level = 1

    def pre(self, ctx):
        return None

    def post(self, ctx, snapshot):
        raise RuntimeError("probe exploded")


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
    expected = exec_step["reported_evidence"]["expected_files"]
    assert expected[str(dst)]["exists"] is True
    assert expected[str(tmp_path / "missing.txt")]["exists"] is False


def test_truncation(tmp_path: Path) -> None:
    with run("truncate", out_dir=str(tmp_path)):
        _long_output()

    receipt = json.loads(_latest_receipt(tmp_path).read_text(encoding="utf-8"))
    step_record = next(step for step in receipt["steps"] if step["name"] == "long_output")
    assert len(step_record["reported_evidence"]) == 2000
    assert step_record["reported_evidence"].endswith("...")


def test_fileprobe_before_after_and_change(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")

    with run("fileprobe-basic", out_dir=str(tmp_path / "out")):
        exec(
            [sys.executable, "-c", "import shutil; shutil.copyfile('a.txt', 'b.txt')"],
            cwd=str(tmp_path),
            probes=[FileProbe("b.txt", level=1)],
        )

    receipt = json.loads(_latest_receipt(tmp_path / "out").read_text(encoding="utf-8"))
    measured = receipt["steps"][0]["measured_evidence"]["FileProbe:b.txt"]
    assert measured["before"]["exists"] is False
    assert measured["after"]["exists"] is True
    assert measured["after"]["size"] == 5
    assert measured["changed"] is True


def test_fileprobe_level2_hash_and_skip_large(tmp_path: Path) -> None:
    small = tmp_path / "small.txt"
    small.write_text("abc", encoding="utf-8")
    large = tmp_path / "large.bin"
    with large.open("wb") as f:
        f.seek(50 * 1024 * 1024)
        f.write(b"x")

    @step("probe-small", probes=[FileProbe(str(small), level=2)])
    def _probe_small() -> None:
        small.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @step("probe-large", probes=[FileProbe(str(large), level=2)])
    def _probe_large() -> None:
        large.chmod(stat.S_IRUSR | stat.S_IWUSR)

    with run("fileprobe-level2", out_dir=str(tmp_path / "out")):
        _probe_small()
        _probe_large()

    receipt = json.loads(_latest_receipt(tmp_path / "out").read_text(encoding="utf-8"))
    small_measured = receipt["steps"][0]["measured_evidence"][f"FileProbe:{small}"]
    assert isinstance(small_measured["after"]["sha256"], str)
    large_measured = receipt["steps"][1]["measured_evidence"][f"FileProbe:{large}"]
    assert large_measured["after"]["sha256"]["skipped"] is True
    assert large_measured["after"]["sha256"]["reason"] == "too_large"


def test_probe_failure_recorded_without_crashing(tmp_path: Path) -> None:
    @step("broken-probe", probes=[BrokenProbe()])
    def _ok_step() -> str:
        return "ok"

    with run("probe-failure", out_dir=str(tmp_path / "out")):
        _ok_step()

    receipt = json.loads(_latest_receipt(tmp_path / "out").read_text(encoding="utf-8"))
    step_data = receipt["steps"][0]
    assert step_data["status"] == "success"
    assert "_probe_error" in step_data["measured_evidence"]["broken"]
