"""Check functions register here with the codes they can emit."""

from __future__ import annotations

from typing import Callable

CHECKS: list[tuple[tuple[str, ...], Callable]] = []


def check(*codes: str):
    def deco(fn):
        CHECKS.append((codes, fn))
        return fn
    return deco
