"""Structured results for composing editing operations without parsing UI text."""
from dataclasses import dataclass

@dataclass(frozen=True)
class EditResult:
    ok: bool
    report: str
    element: int | None = None
