from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _brief_evidence(step: dict) -> str:
    evidence = step.get("evidence")
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
