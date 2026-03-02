from __future__ import annotations

import contextvars
import dataclasses
import datetime as dt
import json
import os
import pathlib
import subprocess
import traceback
import uuid
from typing import Any

from .probes import Probe

ISO_UTC = "%Y-%m-%dT%H:%M:%S.%fZ"

_current_run: contextvars.ContextVar["RunContext | None"] = contextvars.ContextVar("runproof_current_run", default=None)


@dataclasses.dataclass
class StepRecord:
    step_id: str
    name: str
    kind: str
    required: bool
    status: str
    started_at: str
    ended_at: str
    duration_ms: int
    args_summary: dict[str, Any] | None = None
    reported_evidence: Any | None = None
    measured_evidence: dict[str, Any] | None = None
    evidence: Any | None = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        if data.get("reported_evidence") is None and data.get("evidence") is not None:
            data["reported_evidence"] = data["evidence"]
        if data.get("evidence") is None and data.get("reported_evidence") is not None:
            data["evidence"] = data["reported_evidence"]
        return data


@dataclasses.dataclass
class RunReceipt:
    version: str
    run_id: str
    name: str
    started_at: str
    ended_at: str
    duration_ms: int
    status: str
    tags: dict[str, Any] | None
    steps: list[StepRecord]

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["steps"] = [step.to_dict() for step in self.steps]
        return data


class RunContext:
    def __init__(self, name: str, out_dir: str | None = None, tags: dict | None = None):
        self.name = name
        self.tags = tags
        self.out_dir = pathlib.Path(out_dir or ".runproof")
        self.run_id = str(uuid.uuid4())
        self.started_dt = _now()
        self.steps: list[StepRecord] = []
        self.required_tracker: dict[str, bool] = {}
        self.integrity_failed = False
        self.run_exception: BaseException | None = None
        self.receipt_path: pathlib.Path | None = None

    def __enter__(self) -> "RunContext":
        self._token = _current_run.set(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.run_exception = exc
        _current_run.reset(self._token)

        ended = _now()
        status = self._compute_status()
        receipt = RunReceipt(
            version="0.2.1",
            run_id=self.run_id,
            name=self.name,
            started_at=_fmt_dt(self.started_dt),
            ended_at=_fmt_dt(ended),
            duration_ms=_duration_ms(self.started_dt, ended),
            status=status,
            tags=self.tags,
            steps=self.steps,
        )
        run_dir = self.out_dir / "runs" / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        self.receipt_path = run_dir / "receipt.json"
        self.receipt_path.write_text(json.dumps(receipt.to_dict(), indent=2), encoding="utf-8")

        meta = {
            "run_id": self.run_id,
            "name": self.name,
            "started_at": receipt.started_at,
            "ended_at": receipt.ended_at,
            "status": status,
            "duration_ms": receipt.duration_ms,
        }
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return False

    def _compute_status(self) -> str:
        any_failed = any(step.status == "failed" for step in self.steps)
        integrity_ok = all(self.required_tracker.values()) if self.required_tracker else True
        if not integrity_ok or self.integrity_failed:
            return "integrity_failed"
        if any_failed or self.run_exception is not None:
            return "failed"
        return "success"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _fmt_dt(value: dt.datetime) -> str:
    return value.strftime(ISO_UTC)


def _duration_ms(started: dt.datetime, ended: dt.datetime) -> int:
    return int((ended - started).total_seconds() * 1000)


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _truncate_jsonable(value: Any, depth: int = 0) -> Any:
    if depth >= 4:
        return "<max_depth_reached>"
    if isinstance(value, str):
        return _truncate_text(value, 2000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_truncate_jsonable(v, depth + 1) for v in value[:50]]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= 50:
                break
            out[str(k)] = _truncate_jsonable(v, depth + 1)
        return out
    return {"_type": type(value).__name__, "_repr": _truncate_text(repr(value), 500)}


def _is_json_primitive(value: Any) -> bool:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return True
    if isinstance(value, list):
        return all(_is_json_primitive(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(k, (str, int, float, bool)) and _is_json_primitive(v) for k, v in value.items())
    return False


def _summarize_value(value: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"type": type(value).__name__}
    if isinstance(value, (str, list, tuple, dict, set, bytes, bytearray)):
        summary["size"] = len(value)
    return summary


def _args_summary(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "args": [_summarize_value(arg) for arg in args],
        "kwargs": {key: _summarize_value(val) for key, val in kwargs.items()},
    }
    if os.getenv("RUNPROOF_CAPTURE_ARGS") == "1":
        summary["args_values"] = [_truncate_text(repr(arg), 500) for arg in args]
        summary["kwargs_values"] = {k: _truncate_text(repr(v), 500) for k, v in kwargs.items()}
    return summary


def _error_dict(exc: BaseException) -> dict[str, str]:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": _truncate_text(tb, 2000),
    }


def _record_step(step: StepRecord) -> None:
    ctx = _current_run.get()
    if ctx is None:
        return
    ctx.steps.append(step)
    if step.required:
        key = f"{step.kind}:{step.name}"
        prev = ctx.required_tracker.get(key, False)
        ctx.required_tracker[key] = prev or step.status == "success"


def _probe_ctx(
    *,
    step_name: str,
    step_kind: str,
    started_at: str,
    cwd: str | None = None,
    cmd: list[str] | str | None = None,
) -> dict[str, Any]:
    run_ctx = _current_run.get()
    return {
        "step_name": step_name,
        "step_kind": step_kind,
        "cwd": cwd,
        "cmd": cmd,
        "run_id": run_ctx.run_id if run_ctx else None,
        "started_at": started_at,
        "observed_at": _fmt_dt(_now()),
    }


def _run_probe_post(
    probes: list[Probe],
    probe_ctx: dict[str, Any],
    snapshots: dict[str, Any],
) -> dict[str, Any]:
    measured: dict[str, Any] = {}
    for probe in probes:
        try:
            measured[probe.name] = _truncate_jsonable(probe.post(probe_ctx, snapshots.get(probe.name)))
        except Exception as exc:  # noqa: BLE001
            measured[probe.name] = {
                "_probe_error": f"{type(exc).__name__}: {exc}",
                "traceback": _truncate_text(traceback.format_exc(), 2000),
            }
    return measured


def _apply_probe_mismatch_policy(record: StepRecord) -> None:
    measured = record.measured_evidence
    if not isinstance(measured, dict):
        return

    mismatches: list[dict[str, Any]] = []
    for probe_name, evidence in measured.items():
        if not isinstance(evidence, dict):
            continue
        assertion = evidence.get("assertion")
        if not isinstance(assertion, dict):
            continue
        if assertion.get("ok", True):
            continue
        mismatches.append(
            {
                "probe": probe_name,
                "on_mismatch": evidence.get("on_mismatch", "record"),
                "reasons": assertion.get("reasons") or [],
            }
        )

    if not mismatches:
        return

    run_ctx = _current_run.get()
    if run_ctx is not None and any(item["on_mismatch"] == "fail_run" for item in mismatches):
        run_ctx.integrity_failed = True

    step_mismatch = next((item for item in mismatches if item["on_mismatch"] == "fail_step"), None)
    if step_mismatch and record.status != "failed":
        record.status = "failed"
        reasons = [str(reason) for reason in step_mismatch["reasons"]]
        message = reasons[0] if reasons else "probe assertion mismatch"
        record.error = {
            "type": "ProbeMismatch",
            "message": message,
            "probe": str(step_mismatch["probe"]),
            "reasons": reasons,
        }


def run(name: str, *, out_dir: str | None = None, tags: dict | None = None) -> RunContext:
    return RunContext(name=name, out_dir=out_dir, tags=tags)


def step(name: str | None = None, *, required: bool = False, probes: list[Probe] | None = None):
    def decorator(func):
        step_name = name or func.__name__

        def wrapper(*args, **kwargs):
            ctx = _current_run.get()
            if ctx is None:
                return func(*args, **kwargs)

            started = _now()
            record = StepRecord(
                step_id=str(uuid.uuid4()),
                name=step_name,
                kind="function",
                required=required,
                status="success",
                started_at=_fmt_dt(started),
                ended_at=_fmt_dt(started),
                duration_ms=0,
                args_summary=_args_summary(args, kwargs),
            )
            active_probes = probes or []
            probe_ctx = _probe_ctx(step_name=step_name, step_kind="function", started_at=record.started_at)
            snapshots: dict[str, Any] = {}
            for probe in active_probes:
                try:
                    snapshots[probe.name] = probe.pre(probe_ctx)
                except Exception as exc:  # noqa: BLE001
                    snapshots[probe.name] = {
                        "_probe_error": f"{type(exc).__name__}: {exc}",
                        "traceback": _truncate_text(traceback.format_exc(), 2000),
                    }
            try:
                result = func(*args, **kwargs)
                if _is_json_primitive(result):
                    record.reported_evidence = _truncate_jsonable(result)
                else:
                    record.reported_evidence = {"_type": type(result).__name__, "_repr": _truncate_text(repr(result), 500)}
                record.evidence = record.reported_evidence
                return result
            except Exception as exc:  # noqa: BLE001
                record.status = "failed"
                record.error = _error_dict(exc)
                raise
            finally:
                if active_probes:
                    record.measured_evidence = _run_probe_post(active_probes, probe_ctx, snapshots)
                    _apply_probe_mismatch_policy(record)
                ended = _now()
                record.ended_at = _fmt_dt(ended)
                record.duration_ms = _duration_ms(started, ended)
                _record_step(record)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        wrapper.__module__ = func.__module__
        return wrapper

    return decorator


def exec(
    cmd: list[str] | str,
    *,
    name: str | None = None,
    required: bool = False,
    cwd: str | None = None,
    env: dict | None = None,
    timeout: float | None = None,
    shell: bool = False,
    capture_output: bool = True,
    expect_files: list[str] | None = None,
    probes: list[Probe] | None = None,
):
    step_name = name or (cmd if isinstance(cmd, str) else " ".join(cmd))
    started = _now()
    record = StepRecord(
        step_id=str(uuid.uuid4()),
        name=step_name,
        kind="exec",
        required=required,
        status="success",
        started_at=_fmt_dt(started),
        ended_at=_fmt_dt(started),
        duration_ms=0,
    )
    active_probes = probes or []
    probe_ctx = _probe_ctx(step_name=step_name, step_kind="exec", started_at=record.started_at, cwd=cwd, cmd=cmd)
    snapshots: dict[str, Any] = {}
    for probe in active_probes:
        try:
            snapshots[probe.name] = probe.pre(probe_ctx)
        except Exception as exc:  # noqa: BLE001
            snapshots[probe.name] = {
                "_probe_error": f"{type(exc).__name__}: {exc}",
                "traceback": _truncate_text(traceback.format_exc(), 2000),
            }
    try:
        completed = subprocess.run(  # noqa: S603
            cmd,
            cwd=cwd,
            env=env,
            timeout=timeout,
            shell=shell,
            capture_output=capture_output,
            text=True,
            check=False,
        )
        evidence = {
            "cmd": cmd,
            "cwd": cwd,
            "exit_code": completed.returncode,
            "stdout_tail": _truncate_text(completed.stdout or "", 2000),
            "stderr_tail": _truncate_text(completed.stderr or "", 2000),
        }
        if expect_files:
            expected_files = {}
            for file_path in expect_files:
                p = pathlib.Path(file_path)
                file_info: dict[str, Any] = {"exists": p.exists()}
                if p.exists():
                    stat = p.stat()
                    file_info["stat"] = {
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "mode": stat.st_mode,
                    }
                expected_files[file_path] = file_info
            evidence["expected_files"] = expected_files
        record.reported_evidence = evidence
        record.evidence = record.reported_evidence
        if completed.returncode != 0:
            raise subprocess.CalledProcessError(
                completed.returncode,
                cmd,
                output=completed.stdout,
                stderr=completed.stderr,
            )
        return completed
    except Exception as exc:  # noqa: BLE001
        record.status = "failed"
        record.error = _error_dict(exc)
        raise
    finally:
        if active_probes:
            record.measured_evidence = _run_probe_post(active_probes, probe_ctx, snapshots)
            _apply_probe_mismatch_policy(record)
        ended = _now()
        record.ended_at = _fmt_dt(ended)
        record.duration_ms = _duration_ms(started, ended)
        _record_step(record)
