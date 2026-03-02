from __future__ import annotations

from collections.abc import Iterable

_required_registry: list[str] = []


def register_required_step(step_key: str) -> None:
    if step_key not in _required_registry:
        _required_registry.append(step_key)


def get_registered_required_steps() -> list[str]:
    return list(_required_registry)


def merge_required_steps(explicit: Iterable[str] | None, discovered: Iterable[str] | None) -> list[str]:
    merged: list[str] = []
    for key in list(explicit or []) + list(discovered or []):
        normalized = str(key)
        if normalized not in merged:
            merged.append(normalized)
    return merged


def reset_registry() -> None:
    _required_registry.clear()
