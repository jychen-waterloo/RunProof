from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


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
            lines.append(
                f"{probe_name} before:{before_state} after:{after_state}{size_part} changed={evidence.get('changed')}"
            )
        else:
            lines.append(f"{probe_name}: keys={','.join(list(evidence.keys())[:3])}")
    return lines

def view(receipt_path: str) -> int:
    path = Path(receipt_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    print(f"Run: {data['name']} ({data['run_id']})")
    print(f"Status: {data['status']}")
    print(f"Started: {data['started_at']}")
    print(f"Ended: {data['ended_at']}")
    print(f"Duration: {data['duration_ms']} ms")
    print("Steps:")
    for step in data.get("steps", []):
        mark = "[x]" if step.get("status") == "success" else "[ ]"
        brief = _brief_evidence(step)
        print(f"  {mark} {step.get('name')} ({step.get('kind')}, required={step.get('required')}) {brief}")
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
