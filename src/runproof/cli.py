from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path


ISO_UTC = "%Y-%m-%dT%H:%M:%S.%fZ"


def _brief_evidence(step: dict) -> str:
    evidence = step.get("reported_evidence", step.get("evidence"))
    if evidence is None:
        return ""
    if isinstance(evidence, dict):
        if "exit_code" in evidence:
            return f"exit={evidence.get('exit_code')}"
        if "_type" in evidence:
            return f"type={evidence.get('_type')}"
        keys = ",".join(list(evidence.keys())[:3])
        return f"keys={keys}"
    return str(type(evidence).__name__)


def _summarize_measured(step: dict) -> list[str]:
    measured = step.get("measured_evidence")
    if not isinstance(measured, dict):
        return []

    lines: list[str] = []
    for probe_name, evidence in measured.items():
        if not isinstance(evidence, dict):
            lines.append(f"{probe_name}: <non-dict evidence>")
            continue
        if "_probe_error" in evidence:
            lines.append(f"{probe_name}: ERROR {evidence.get('_probe_error')}")
            continue

        before = evidence.get("before", {})
        after = evidence.get("after", {})
        if isinstance(before, dict) and isinstance(after, dict):
            before_state = "exists" if before.get("exists") else "missing"
            after_state = "exists" if after.get("exists") else "missing"
            size = after.get("size")
            size_part = f" size={size}" if size is not None else ""
            assertion = evidence.get("assertion")
            mismatch = ""
            if isinstance(assertion, dict) and assertion.get("ok") is False:
                reasons = assertion.get("reasons") or []
                reason = reasons[0] if reasons else "assertion mismatch"
                mismatch = f" MISMATCH ({reason})"
            lines.append(
                f"{probe_name} before:{before_state} after:{after_state}{size_part} changed={evidence.get('changed')}{mismatch}"
            )
        else:
            lines.append(f"{probe_name}: keys={','.join(list(evidence.keys())[:3])}")
    return lines


def _parse_time(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, ISO_UTC).replace(tzinfo=dt.timezone.utc)


def _step_sort_key(step: dict) -> tuple[dt.datetime, int]:
    started_raw = step.get("started_at")
    try:
        started = _parse_time(started_raw)
    except Exception:  # noqa: BLE001
        started = dt.datetime.max.replace(tzinfo=dt.timezone.utc)
    return (started, int(step.get("seq", 0)))


def _relative_window(step: dict, run_start: dt.datetime) -> str:
    try:
        started = _parse_time(step["started_at"])
        ended = _parse_time(step["ended_at"])
    except Exception:  # noqa: BLE001
        return ""
    rel_start = int((started - run_start).total_seconds() * 1000)
    rel_end = int((ended - run_start).total_seconds() * 1000)
    return f" [+{rel_start}ms → +{rel_end}ms]"


def view(receipt_path: str) -> int:
    path = Path(receipt_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    print(f"Run: {data['name']} ({data['run_id']})")
    print(f"Status: {data['status']}")
    print(f"Started: {data['started_at']}")
    print(f"Ended: {data['ended_at']}")
    print(f"Duration: {data['duration_ms']} ms")
    missing = data.get("missing_required_steps") or []
    if missing:
        print(f"Missing required steps: {', '.join(missing)}")
    print("Steps:")
    print("  Displayed in start-time order; steps may overlap due to concurrency.")
    run_start = _parse_time(data["started_at"])
    sorted_steps = sorted(data.get("steps", []), key=_step_sort_key)
    for step in sorted_steps:
        mark = "[x]" if step.get("status") == "success" else "[ ]"
        brief = _brief_evidence(step)
        rel = _relative_window(step, run_start)
        print(f"  {mark} {step.get('name')} ({step.get('kind')}, required={step.get('required')}) {brief}{rel}")
        for measured_line in _summarize_measured(step):
            print(f"      - {measured_line}")

    return 0 if data.get("status") == "success" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="runproof")
    subparsers = parser.add_subparsers(dest="command", required=True)

    view_parser = subparsers.add_parser("view", help="View a run receipt")
    view_parser.add_argument("receipt", help="Path to receipt.json")

    args = parser.parse_args(argv)
    if args.command == "view":
        return view(args.receipt)
    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
