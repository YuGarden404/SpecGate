from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import specgate.workspace_fs as workspace_fs

TEXT_SUFFIXES = {".md", ".html", ".css", ".js", ".txt", ".toml", ".json", ".jsonl"}
EXCLUDED_DIRS = {".git", "__pycache__", "runs", "reports", "eval-runs"}
EXCLUDED_FILES = {"memory.json"}
DEFAULT_BUDGET_CHARS = 12000
TRUNCATION_SUFFIX = "\n...[truncated by SpecGate context budget]\n"


@dataclass(frozen=True)
class ContextFile:
    path: str
    status: str
    reason: str
    chars: int
    priority: int
    content: str = ""


@dataclass(frozen=True)
class ContextSelection:
    files: list[ContextFile]
    budget_chars: int
    used_chars: int


def _is_under_excluded_dir(relative_path: str) -> bool:
    return any(
        part in EXCLUDED_DIRS or part.startswith(".")
        for part in relative_path.split("/")[:-1]
    )


def _priority(relative_path: str) -> int:
    names = {
        "TASK_SPEC.md": 0,
        "CHECKLIST.md": 1,
        "README.md": 2,
        "index.html": 3,
    }
    if relative_path in names:
        return names[relative_path]
    if relative_path.endswith(".md"):
        return 10
    if relative_path.endswith(".html"):
        return 20
    if relative_path.endswith((".css", ".js")):
        return 30
    return 40


def _scan_files(root: Path) -> list[str]:
    return list(workspace_fs.iter_workspace_files(root))


def select_context_files(
    root: Path,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
    allowed_read_paths: set[str] | None = None,
) -> ContextSelection:
    if budget_chars <= 0:
        raise ValueError("budget_chars must be positive")

    candidates: list[tuple[int, str]] = []
    skipped: list[ContextFile] = []

    try:
        scanned_files = _scan_files(root)
    except workspace_fs.WorkspacePathError as exc:
        scanned_files = []
        skipped.append(
            ContextFile(
                "<workspace>",
                "skipped",
                f"{exc.rule_family}: {exc.message}",
                0,
                0,
            )
        )

    for rel in scanned_files:
        priority = _priority(rel)
        if allowed_read_paths is not None and rel not in allowed_read_paths:
            continue
        if rel in EXCLUDED_FILES:
            skipped.append(ContextFile(rel, "skipped", "managed memory file", 0, priority))
            continue
        if _is_under_excluded_dir(rel):
            skipped.append(ContextFile(rel, "skipped", "excluded runtime or hidden directory", 0, priority))
            continue
        if Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            skipped.append(ContextFile(rel, "skipped", "unsupported file suffix", 0, priority))
            continue
        candidates.append((priority, rel))

    selected: list[ContextFile] = []
    used_chars = 0

    for priority, rel in sorted(candidates):
        try:
            content = workspace_fs.read_workspace_text(root, rel, encoding="utf-8")
        except UnicodeDecodeError:
            selected.append(ContextFile(rel, "skipped", "file is not utf-8 text", 0, priority))
            continue
        except workspace_fs.WorkspacePathError as exc:
            selected.append(
                ContextFile(
                    rel,
                    "skipped",
                    f"{exc.rule_family}: {exc.message}",
                    0,
                    priority,
                )
            )
            continue
        except OSError as exc:
            selected.append(ContextFile(rel, "skipped", f"read failed: {exc}", 0, priority))
            continue

        remaining = budget_chars - used_chars
        if remaining <= 0:
            selected.append(ContextFile(rel, "skipped", "context budget exhausted", len(content), priority))
            continue
        if len(content) <= remaining:
            selected.append(ContextFile(rel, "selected", "selected within context budget", len(content), priority, content))
            used_chars += len(content)
            continue

        if remaining > len(TRUNCATION_SUFFIX):
            truncated = content[: remaining - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX
            selected.append(ContextFile(rel, "truncated", "truncated to fit context budget", len(content), priority, truncated))
            used_chars += len(truncated)
        else:
            selected.append(ContextFile(rel, "skipped", "context budget exhausted", len(content), priority))

    return ContextSelection(sorted(selected + skipped, key=lambda item: (item.priority, item.path)), budget_chars, used_chars)
