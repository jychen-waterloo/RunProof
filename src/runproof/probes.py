from __future__ import annotations

import dataclasses
import hashlib
import os
import pathlib
from typing import Any, Protocol

MAX_HASH_SIZE_BYTES = 50 * 1024 * 1024


class Probe(Protocol):
    name: str
    level: int

    def pre(self, ctx: dict[str, Any]) -> Any: ...

    def post(self, ctx: dict[str, Any], snapshot: Any) -> dict[str, Any]: ...


@dataclasses.dataclass
class FileProbe:
    path: str
    level: int = 1
    name: str | None = None
    expect: dict[str, Any] | None = None
    on_mismatch: str = "record"

    def __post_init__(self) -> None:
        self.name = self.name or f"FileProbe:{self.path}"
        if self.on_mismatch not in {"record", "fail_step", "fail_run"}:
            raise ValueError("on_mismatch must be one of: record, fail_step, fail_run")

    def _resolve(self, ctx: dict[str, Any]) -> pathlib.Path:
        cwd = pathlib.Path(ctx.get("cwd") or os.getcwd())
        candidate = pathlib.Path(self.path)
        if candidate.is_absolute():
            return candidate
        return cwd / candidate

    def _snapshot_file(self, resolved_path: pathlib.Path) -> dict[str, Any]:
        info: dict[str, Any] = {
            "path": str(resolved_path),
            "exists": resolved_path.exists(),
        }
        if not info["exists"]:
            return info

        stat = resolved_path.stat()
        info.update(
            {
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "mode": stat.st_mode,
            }
        )
        if self.level >= 2:
            info["sha256"] = self._maybe_sha256(resolved_path, stat.st_size)
        return info

    def _maybe_sha256(self, resolved_path: pathlib.Path, size: int) -> str | dict[str, Any]:
        if size > MAX_HASH_SIZE_BYTES:
            return {"skipped": True, "reason": "too_large"}

        hasher = hashlib.sha256()
        with resolved_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def pre(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return self._snapshot_file(self._resolve(ctx))

    def _evaluate_assertion(self, before: dict[str, Any], after: dict[str, Any], changed: bool) -> dict[str, Any]:
        expect = self.expect or {}
        reasons: list[str] = []
        details: dict[str, Any] = {}

        expected_exists = expect.get("exists")
        if expected_exists is not None and after.get("exists") != expected_exists:
            reasons.append(f"expected exists={expected_exists} but was {after.get('exists')}")
            details["exists"] = {"expected": expected_exists, "actual": after.get("exists")}

        if after.get("exists"):
            actual_size = after.get("size")
            min_size = expect.get("min_size")
            if min_size is not None and (actual_size is None or actual_size < min_size):
                reasons.append(f"expected size>={min_size} but was {actual_size}")
                details["min_size"] = {"expected": min_size, "actual": actual_size}

            max_size = expect.get("max_size")
            if max_size is not None and (actual_size is None or actual_size > max_size):
                reasons.append(f"expected size<={max_size} but was {actual_size}")
                details["max_size"] = {"expected": max_size, "actual": actual_size}

            size_eq = expect.get("size_eq")
            if size_eq is not None and actual_size != size_eq:
                reasons.append(f"expected size=={size_eq} but was {actual_size}")
                details["size_eq"] = {"expected": size_eq, "actual": actual_size}

        expected_changed = expect.get("changed")
        if expected_changed is not None and changed != expected_changed:
            reasons.append(f"expected changed={expected_changed} but was {changed}")
            details["changed"] = {"expected": expected_changed, "actual": changed}

        if "size_delta_min" in expect or "size_delta_max" in expect:
            before_size = before.get("size") if before.get("exists") else None
            after_size = after.get("size") if after.get("exists") else None
            if before_size is None or after_size is None:
                reasons.append("size delta unavailable because file was missing")
                details["size_delta"] = {"before": before_size, "after": after_size}
            else:
                delta = after_size - before_size
                size_delta_min = expect.get("size_delta_min")
                if size_delta_min is not None and delta < size_delta_min:
                    reasons.append(f"expected size_delta>={size_delta_min} but was {delta}")
                    details["size_delta_min"] = {"expected": size_delta_min, "actual": delta}
                size_delta_max = expect.get("size_delta_max")
                if size_delta_max is not None and delta > size_delta_max:
                    reasons.append(f"expected size_delta<={size_delta_max} but was {delta}")
                    details["size_delta_max"] = {"expected": size_delta_max, "actual": delta}

        expected_sha = expect.get("sha256")
        if expected_sha is not None:
            actual_sha = after.get("sha256") if after.get("exists") else None
            if isinstance(actual_sha, dict) and actual_sha.get("skipped"):
                reasons.append("expected sha256 but hash was skipped")
                details["sha256"] = {"expected": expected_sha, "actual": actual_sha}
            elif actual_sha != expected_sha:
                reasons.append(f"expected sha256={expected_sha} but was {actual_sha}")
                details["sha256"] = {"expected": expected_sha, "actual": actual_sha}

        return {"ok": len(reasons) == 0, "reasons": reasons, "details": details}

    def post(self, ctx: dict[str, Any], snapshot: Any) -> dict[str, Any]:
        before = snapshot if isinstance(snapshot, dict) else {"invalid_snapshot": True}
        after = self._snapshot_file(self._resolve(ctx))

        changed = before.get("exists") != after.get("exists")
        for key in ("size", "mtime", "sha256"):
            if before.get(key) != after.get(key):
                changed = True
                break

        assertion = self._evaluate_assertion(before, after, changed)

        return {
            "path": self.path,
            "level": self.level,
            "on_mismatch": self.on_mismatch,
            "expect": self.expect or {},
            "before": before,
            "after": after,
            "changed": changed,
            "assertion": assertion,
        }
