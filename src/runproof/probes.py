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

    def __post_init__(self) -> None:
        self.name = self.name or f"FileProbe:{self.path}"

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

    def post(self, ctx: dict[str, Any], snapshot: Any) -> dict[str, Any]:
        before = snapshot if isinstance(snapshot, dict) else {"invalid_snapshot": True}
        after = self._snapshot_file(self._resolve(ctx))

        changed = before.get("exists") != after.get("exists")
        for key in ("size", "mtime", "sha256"):
            if before.get(key) != after.get(key):
                changed = True
                break

        return {
            "path": self.path,
            "level": self.level,
            "before": before,
            "after": after,
            "changed": changed,
        }
