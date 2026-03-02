from __future__ import annotations

import asyncio
import json
import stat
import sys
from pathlib import Path

import pytest

from runproof import FileProbe, exec, reset_registry, run, step


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
    assert receipt["status"] == "failed"


def test_ghost_step_bypass_fixed(tmp_path: Path) -> None:
    with run("ghost-bypass", out_dir=str(tmp_path), require_steps=["function:never_called"]):
        pass

    receipt = json.loads(_latest_receipt(tmp_path).read_text(encoding="utf-8"))
    assert receipt["status"] == "integrity_failed"
    assert receipt["missing_required_steps"] == ["function:never_called"]


def test_required_step_success(tmp_path: Path) -> None:
    with run("required-success", out_dir=str(tmp_path), require_steps=["function:required_ok"]):
        _required_ok()

    receipt = json.loads(_latest_receipt(tmp_path).read_text(encoding="utf-8"))
    assert receipt["status"] == "success"
    assert receipt["missing_required_steps"] == []


def test_auto_contract_append_only(tmp_path: Path) -> None:
    reset_registry()

    @step("auto_required", required=True)
    def _auto_required() -> None:
        return None

    with run("auto-contract-missing", out_dir=str(tmp_path / "one"), auto_contract=True):
        pass

    one = json.loads(_latest_receipt(tmp_path / "one").read_text(encoding="utf-8"))
    assert one["status"] == "integrity_failed"
    assert "function:auto_required" in one["missing_required_steps"]

    with run(
        "auto-contract-merge",
        out_dir=str(tmp_path / "two"),
        require_steps=["function:explicit_only"],
        auto_contract=True,
    ):
        pass

    two = json.loads(_latest_receipt(tmp_path / "two").read_text(encoding="utf-8"))
    assert two["status"] == "integrity_failed"
    assert two["missing_required_steps"] == ["function:explicit_only", "function:auto_required"]


def test_exec_expect_files_routed_to_fileprobe(tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"

    with run("exec-files", out_dir=str(tmp_path / "out")):
        exec([sys.executable, "-c", "pass"], cwd=str(tmp_path), expect_files=[str(missing)])

    receipt = json.loads(_latest_receipt(tmp_path / "out").read_text(encoding="utf-8"))
    exec_step = next(step_data for step_data in receipt["steps"] if step_data["kind"] == "exec")
    assert "expected_files" not in exec_step["reported_evidence"]
    measured = exec_step["measured_evidence"][f"FileProbe:{missing}"]
    assert measured["after"]["exists"] is False


def test_truncation(tmp_path: Path) -> None:
    with run("truncate", out_dir=str(tmp_path)):
        _long_output()

    receipt = json.loads(_latest_receipt(tmp_path).read_text(encoding="utf-8"))
    step_record = next(step_data for step_data in receipt["steps"] if step_data["name"] == "long_output")
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


def test_fileprobe_record_mismatch_does_not_fail_step_or_run(tmp_path: Path) -> None:
    with run("fileprobe-record-mismatch", out_dir=str(tmp_path / "out")):
        exec(
            [sys.executable, "-c", "pass"],
            cwd=str(tmp_path),
            probes=[FileProbe("b.txt", expect={"exists": True}, on_mismatch="record")],
        )

    receipt = json.loads(_latest_receipt(tmp_path / "out").read_text(encoding="utf-8"))
    assert receipt["status"] == "success"
    step_data = receipt["steps"][0]
    assert step_data["status"] == "success"
    measured = step_data["measured_evidence"]["FileProbe:b.txt"]
    assert measured["assertion"]["ok"] is False
    assert measured["assertion"]["reasons"]


def test_fileprobe_fail_step_on_mismatch(tmp_path: Path) -> None:
    with run("fileprobe-fail-step", out_dir=str(tmp_path / "out")):
        exec(
            [sys.executable, "-c", "pass"],
            cwd=str(tmp_path),
            probes=[FileProbe("b.txt", expect={"exists": True}, on_mismatch="fail_step")],
        )

    receipt = json.loads(_latest_receipt(tmp_path / "out").read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    step_data = receipt["steps"][0]
    assert step_data["status"] == "failed"
    assert step_data["error"]["type"] == "ProbeMismatch"


def test_fileprobe_fail_run_on_mismatch_sets_integrity_failed(tmp_path: Path) -> None:
    with run("fileprobe-fail-run", out_dir=str(tmp_path / "out")):
        exec(
            [sys.executable, "-c", "pass"],
            cwd=str(tmp_path),
            probes=[FileProbe("b.txt", expect={"exists": True}, on_mismatch="fail_run")],
        )

    receipt = json.loads(_latest_receipt(tmp_path / "out").read_text(encoding="utf-8"))
    assert receipt["status"] == "integrity_failed"
    step_data = receipt["steps"][0]
    assert step_data["status"] == "success"


def test_fileprobe_size_expectations(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("abcd", encoding="utf-8")

    with run("fileprobe-size-expect", out_dir=str(tmp_path / "out")):
        exec(
            [sys.executable, "-c", "pass"],
            cwd=str(tmp_path),
            probes=[FileProbe("data.txt", expect={"min_size": 4, "max_size": 4, "size_eq": 4})],
        )
        exec(
            [sys.executable, "-c", "pass"],
            cwd=str(tmp_path),
            probes=[FileProbe("data.txt", expect={"min_size": 10}, on_mismatch="record")],
        )

    receipt = json.loads(_latest_receipt(tmp_path / "out").read_text(encoding="utf-8"))
    ok_measured = receipt["steps"][0]["measured_evidence"]["FileProbe:data.txt"]
    bad_measured = receipt["steps"][1]["measured_evidence"]["FileProbe:data.txt"]
    assert ok_measured["assertion"]["ok"] is True
    assert bad_measured["assertion"]["ok"] is False


def test_async_step_awaited_records_success(tmp_path: Path) -> None:
    reset_registry()

    @step("async-required", required=True)
    async def _async_required() -> dict[str, bool]:
        await asyncio.sleep(0.02)
        return {"ok": True}

    async def _runner() -> None:
        with run("async-step", out_dir=str(tmp_path / "out"), auto_contract=True):
            await _async_required()

    asyncio.run(_runner())

    receipt = json.loads(_latest_receipt(tmp_path / "out").read_text(encoding="utf-8"))
    assert receipt["status"] == "success"
    step_data = receipt["steps"][0]
    assert step_data["status"] == "success"
    assert step_data["duration_ms"] > 0


def test_async_step_not_awaited_does_not_record(tmp_path: Path) -> None:
    @step("async-not-awaited")
    async def _async_not_awaited() -> None:
        await asyncio.sleep(0)

    with run("async-misuse", out_dir=str(tmp_path)):
        coro = _async_not_awaited()
        coro.close()

    receipt = json.loads(_latest_receipt(tmp_path).read_text(encoding="utf-8"))
    assert receipt["steps"] == []


def test_async_concurrency_seq_and_time_fields(tmp_path: Path) -> None:
    @step("async-a")
    async def _a() -> str:
        await asyncio.sleep(0.02)
        return "a"

    @step("async-b")
    async def _b() -> str:
        await asyncio.sleep(0.01)
        return "b"

    async def _runner() -> None:
        with run("async-gather", out_dir=str(tmp_path / "out")):
            await asyncio.gather(_a(), _b())

    asyncio.run(_runner())

    receipt = json.loads(_latest_receipt(tmp_path / "out").read_text(encoding="utf-8"))
    assert len(receipt["steps"]) == 2
    seqs = [step_data["seq"] for step_data in receipt["steps"]]
    assert seqs == sorted(seqs)
    for step_data in receipt["steps"]:
        assert "started_at" in step_data
        assert "ended_at" in step_data
    sorted_view = sorted(receipt["steps"], key=lambda s: (s["started_at"], s["seq"]))
    assert [s["name"] for s in sorted_view] == [s["name"] for s in sorted(sorted_view, key=lambda s: (s["started_at"], s["seq"]))]
