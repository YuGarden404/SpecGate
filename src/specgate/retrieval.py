from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

import specgate.workspace_fs as workspace_fs

DEFAULT_SUFFIXES = frozenset({".md", ".txt", ".toml", ".json", ".jsonl", ".py", ".html", ".css", ".js"})
EXCLUDED_DIRS = frozenset({".git", "__pycache__", "runs", "reports", "eval-runs"})
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*|[\u4e00-\u9fff]+")
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "be",
        "build",
        "failed",
        "for",
        "include",
        "is",
        "missing",
        "must",
        "of",
        "the",
        "to",
    }
)


@dataclass(frozen=True)
class RetrievalConfig:
    top_k: int = 6
    chunk_lines: int = 40
    chunk_overlap_lines: int = 5
    max_chunk_chars: int = 3000
    budget_chars: int = 9000
    include_suffixes: frozenset[str] = field(default_factory=lambda: DEFAULT_SUFFIXES)
    exclude_dirs: frozenset[str] = field(default_factory=lambda: EXCLUDED_DIRS)


@dataclass(frozen=True)
class RetrievedChunk:
    path: str
    start_line: int
    end_line: int
    text: str
    score: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    reason: str = ""
    token_estimate: int = 0
    trusted: bool = False


@dataclass(frozen=True)
class RetrievalResult:
    query_terms: list[str]
    candidate_count: int
    selected_chunks: list[RetrievedChunk]
    budget_chars: int
    used_chars: int
    dropped_reasons: list[str]


def build_query_terms(task_spec: str, checklist: str, gate_feedback: str = "") -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in _tokens("\n".join([task_spec, checklist, gate_feedback])):
        if token in STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def chunk_text(path: str, text: str, chunk_lines: int, overlap_lines: int, max_chunk_chars: int) -> list[RetrievedChunk]:
    if chunk_lines <= 0:
        raise ValueError("chunk_lines must be positive")
    if overlap_lines < 0:
        raise ValueError("overlap_lines must be non-negative")
    if overlap_lines >= chunk_lines:
        raise ValueError("overlap_lines must be smaller than chunk_lines")
    if max_chunk_chars <= 0:
        raise ValueError("max_chunk_chars must be positive")

    lines = text.splitlines()
    chunks: list[RetrievedChunk] = []
    start = 0
    step = chunk_lines - overlap_lines
    normalized_path = path.replace("\\", "/")

    while start < len(lines):
        end = min(start + chunk_lines, len(lines))
        chunk_body = "\n".join(lines[start:end])
        if len(chunk_body) > max_chunk_chars:
            chunk_body = chunk_body[:max_chunk_chars]
        chunks.append(
            RetrievedChunk(
                path=normalized_path,
                start_line=start + 1,
                end_line=end,
                text=chunk_body,
                token_estimate=_estimate_tokens(chunk_body),
            )
        )
        if end >= len(lines):
            break
        start += step
    return chunks


def score_chunk(chunk: RetrievedChunk, query_terms: list[str]) -> RetrievedChunk:
    chunk_terms = set(_tokens(chunk.text))
    matched = sorted({term for term in query_terms if term in chunk_terms})
    score = float(len(matched))
    if chunk.path in {"TASK_SPEC.md", "CHECKLIST.md"} and matched:
        score += 0.1
    return RetrievedChunk(
        path=chunk.path,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        text=chunk.text,
        score=score,
        matched_terms=matched,
        reason=f"matched terms: {', '.join(matched)}" if matched else "no query terms matched",
        token_estimate=chunk.token_estimate,
        trusted=chunk.trusted,
    )


def retrieve_chunks(
    root: Path,
    query_terms: list[str],
    config: RetrievalConfig | None = None,
    *,
    top_k: int | None = None,
    allowed_read_paths: set[str] | None = None,
) -> RetrievalResult:
    resolved_config = config or RetrievalConfig()
    if top_k is not None:
        resolved_config = RetrievalConfig(
            top_k=top_k,
            chunk_lines=resolved_config.chunk_lines,
            chunk_overlap_lines=resolved_config.chunk_overlap_lines,
            max_chunk_chars=resolved_config.max_chunk_chars,
            budget_chars=resolved_config.budget_chars,
            include_suffixes=resolved_config.include_suffixes,
            exclude_dirs=resolved_config.exclude_dirs,
        )

    candidates: list[RetrievedChunk] = []
    dropped_reasons: list[str] = []
    try:
        scanned_files = _scan_files(root)
    except workspace_fs.WorkspacePathError as exc:
        scanned_files = []
        dropped_reasons.append(
            f"workspace scan rejected ({exc.rule_family}): {exc.message}"
        )

    for rel in scanned_files:
        if allowed_read_paths is not None and rel not in allowed_read_paths:
            dropped_reasons.append("read path omitted by workspace policy")
            continue
        if _is_under_excluded_dir(rel, resolved_config.exclude_dirs):
            dropped_reasons.append(f"{rel}: excluded directory")
            continue
        if Path(rel).suffix.lower() not in resolved_config.include_suffixes:
            dropped_reasons.append(f"{rel}: unsupported suffix")
            continue
        try:
            text = workspace_fs.read_workspace_text(root, rel, encoding="utf-8")
        except UnicodeDecodeError:
            dropped_reasons.append(f"{rel}: file is not utf-8 text")
            continue
        except workspace_fs.WorkspacePathError as exc:
            dropped_reasons.append(f"{rel}: {exc.rule_family}")
            continue
        except OSError as exc:
            dropped_reasons.append(f"{rel}: read failed: {exc}")
            continue
        candidates.extend(
            score_chunk(chunk, query_terms)
            for chunk in chunk_text(
                rel,
                text,
                resolved_config.chunk_lines,
                resolved_config.chunk_overlap_lines,
                resolved_config.max_chunk_chars,
            )
        )

    ranked = sorted(
        (chunk for chunk in candidates if chunk.score > 0),
        key=lambda chunk: (-chunk.score, chunk.path, chunk.start_line),
    )
    selected: list[RetrievedChunk] = []
    used_chars = 0
    for chunk in ranked:
        if len(selected) >= resolved_config.top_k:
            break
        next_used = used_chars + len(chunk.text)
        if next_used > resolved_config.budget_chars:
            dropped_reasons.append(f"{chunk.path}:{chunk.start_line}: budget exceeded")
            continue
        selected.append(chunk)
        used_chars = next_used

    return RetrievalResult(
        query_terms=query_terms,
        candidate_count=len(candidates),
        selected_chunks=selected,
        budget_chars=resolved_config.budget_chars,
        used_chars=used_chars,
        dropped_reasons=dropped_reasons,
    )


def _tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def _is_under_excluded_dir(relative_path: str, exclude_dirs: frozenset[str]) -> bool:
    return any(
        part in exclude_dirs or part.startswith(".")
        for part in relative_path.split("/")[:-1]
    )


def _scan_files(root: Path) -> list[str]:
    return list(workspace_fs.iter_workspace_files(root))
