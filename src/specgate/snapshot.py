from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import specgate.workspace_fs as workspace_fs

@dataclass(frozen=True)
class FileState:
    exists: bool
    sha256: str | None


@dataclass(frozen=True)
class SnapshotDecision:
    allowed: bool
    reason: str
    rule_family: str = "none"


class FileSnapshot:
    def __init__(self, root: Path, states: dict[str, FileState]):
        self.root = root
        self._states = dict(states)

    @classmethod
    def capture(cls, root: Path, relative_paths: set[str]) -> FileSnapshot:
        states = {path: _read_state(root, path) for path in sorted(relative_paths)}
        return cls(root, states)

    def check_unchanged(self, relative_path: str) -> SnapshotDecision:
        expected = self._states.get(relative_path)
        if expected is None:
            return SnapshotDecision(
                False,
                f"file not in snapshot: {relative_path}",
                "snapshot",
            )

        try:
            current = _read_state(self.root, relative_path)
        except workspace_fs.WorkspacePathError as exc:
            return SnapshotDecision(
                False,
                f"file changed since run started ({exc.rule_family}): {relative_path}",
                exc.rule_family,
            )

        if current == expected:
            return SnapshotDecision(True, "unchanged")
        return SnapshotDecision(
            False,
            f"file changed since run started: {relative_path}",
            "snapshot",
        )

    def update_after_write(self, relative_path: str) -> None:
        if relative_path not in self._states:
            raise KeyError(f"file not in snapshot: {relative_path}")
        self._states[relative_path] = _read_state(self.root, relative_path)


def _read_state(root: Path, relative_path: str) -> FileState:
    state = workspace_fs.workspace_file_state(root, relative_path)
    return FileState(state.exists, state.sha256)
