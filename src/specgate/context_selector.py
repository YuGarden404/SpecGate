from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TEXT_SUFFIXES = {".md", ".html", ".css", ".js", ".txt", ".toml", ".json", ".jsonl"}
EXCLUDED_DIRS = {".git", "__pycache__", "runs", "reports"}
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


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _is_under_excluded_dir(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return any(part in EXCLUDED_DIRS or part.startswith(".") for part in relative.parts[:-1])


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


def _scan_files(root: Path) -> list[Path]:
    return sorted((path for path in root.rglob("*") if path.is_file()), key=lambda item: _relative(item, root))


def select_context_files(root: Path, budget_chars: int = DEFAULT_BUDGET_CHARS) -> ContextSelection:
    if budget_chars <= 0:
        raise ValueError("budget_chars must be positive")

    candidates: list[tuple[int, str, Path]] = []
    skipped: list[ContextFile] = []

    for path in _scan_files(root):
        rel = _relative(path, root)
        priority = _priority(rel)
        if _is_under_excluded_dir(path, root):
            skipped.append(ContextFile(rel, "skipped", "excluded runtime or hidden directory", 0, priority))
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            skipped.append(ContextFile(rel, "skipped", "unsupported file suffix", 0, priority))
            continue
        candidates.append((priority, rel, path))

    selected: list[ContextFile] = []
    used_chars = 0

    for priority, rel, path in sorted(candidates):
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            selected.append(ContextFile(rel, "skipped", "file is not utf-8 text", 0, priority))
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
