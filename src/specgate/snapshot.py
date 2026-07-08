from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileState:
    exists: bool
    sha256: str | None


@dataclass(frozen=True)
class SnapshotDecision:
    allowed: bool
    reason: str


class FileSnapshot:
    def __init__(self, root: Path, states: dict[str, FileState]):
        self.root = root
        self._states = dict(states)

    @classmethod
    def capture(cls, root: Path, relative_paths: set[str]) -> FileSnapshot:
        states = {path: _read_state(root / path) for path in sorted(relative_paths)}
        return cls(root, states)

    def check_unchanged(self, relative_path: str) -> SnapshotDecision:
        expected = self._states.get(relative_path)
        if expected is None:
            return SnapshotDecision(False, f"file not in snapshot: {relative_path}")

        try:
            current = _read_state(self.root / relative_path)
        except OSError:
            return SnapshotDecision(False, f"file changed since run started: {relative_path}")

        if current == expected:
            return SnapshotDecision(True, "unchanged")
        return SnapshotDecision(False, f"file changed since run started: {relative_path}")

    def update_after_write(self, relative_path: str) -> None:
        if relative_path not in self._states:
            raise KeyError(f"file not in snapshot: {relative_path}")
        self._states[relative_path] = _read_state(self.root / relative_path)


def _read_state(path: Path) -> FileState:
    if not path.exists():
        return FileState(False, None)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return FileState(True, digest)
