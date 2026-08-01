from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable

import yaml

import specgate.workspace_fs as workspace_fs
from specgate.workspace_fs import WorkspacePathError


class SkillSource(str, Enum):
    BUILTIN = "builtin"
    WORKSPACE = "workspace"


class SkillRegistryError(ValueError):
    pass


class InvalidSkillError(SkillRegistryError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DuplicateSkillError(SkillRegistryError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__("duplicate_skill_name")


class UnknownSkillError(SkillRegistryError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__("unknown_skill")


class SkillResourceError(SkillRegistryError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SkillCatalogEntry:
    name: str
    description: str
    source: SkillSource


@dataclass(frozen=True)
class SkillInstructions:
    name: str
    description: str
    body: str
    source: SkillSource


@dataclass(frozen=True)
class SkillResource:
    name: str
    path: str
    content: str
    source: SkillSource


@dataclass
class SkillSession:
    agent_run_id: str
    _active_names: set[str] = field(default_factory=set, repr=False)

    def activate(self, name: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise InvalidSkillError("invalid_skill_name")
        self._active_names.add(name.strip())

    @property
    def active_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._active_names))


@dataclass(frozen=True)
class _SkillRecord:
    root: Path
    directory: str
    instructions: SkillInstructions


class SkillRegistry:
    def __init__(
        self,
        *,
        builtin_roots: Iterable[Path] = (),
        workspace_roots: Iterable[Path] = (),
    ) -> None:
        self._records: dict[str, _SkillRecord] = {}
        self._scan_roots(builtin_roots, SkillSource.BUILTIN)
        self._scan_roots(workspace_roots, SkillSource.WORKSPACE)

    def catalog(self) -> tuple[SkillCatalogEntry, ...]:
        return tuple(
            SkillCatalogEntry(
                name=record.instructions.name,
                description=record.instructions.description,
                source=record.instructions.source,
            )
            for _, record in sorted(self._records.items())
        )

    def load(self, name: str) -> SkillInstructions:
        return self._resolve(name).instructions

    def read_resource(self, name: str, path: str) -> SkillResource:
        record = self._resolve(name)
        try:
            normalized = workspace_fs.normalize_workspace_relative(path)
        except WorkspacePathError as exc:
            raise SkillResourceError(exc.rule_family) from exc
        relative = f"{record.directory}/{normalized}"
        try:
            content = workspace_fs.read_workspace_text(
                record.root,
                relative,
                encoding="utf-8",
                errors="strict",
            )
        except UnicodeDecodeError as exc:
            raise SkillResourceError("invalid_utf8") from exc
        except WorkspacePathError as exc:
            raise SkillResourceError(exc.rule_family) from exc
        return SkillResource(
            name=record.instructions.name,
            path=normalized,
            content=content,
            source=record.instructions.source,
        )

    def _scan_roots(
        self,
        roots: Iterable[Path],
        source: SkillSource,
    ) -> None:
        for root_value in roots:
            root = Path(root_value)
            try:
                files = tuple(workspace_fs.iter_workspace_files(root))
            except WorkspacePathError as exc:
                raise InvalidSkillError(exc.rule_family) from exc
            for relative in sorted(files):
                parts = relative.split("/")
                if len(parts) != 2 or parts[1] != "SKILL.md":
                    continue
                instructions = self._read_instructions(
                    root,
                    relative,
                    source,
                )
                if instructions.name in self._records:
                    raise DuplicateSkillError(instructions.name)
                self._records[instructions.name] = _SkillRecord(
                    root=root,
                    directory=parts[0],
                    instructions=instructions,
                )

    @staticmethod
    def _read_instructions(
        root: Path,
        relative: str,
        source: SkillSource,
    ) -> SkillInstructions:
        try:
            text = workspace_fs.read_workspace_text(
                root,
                relative,
                encoding="utf-8",
                errors="strict",
            )
        except UnicodeDecodeError as exc:
            raise InvalidSkillError("invalid_utf8") from exc
        except WorkspacePathError as exc:
            raise InvalidSkillError(exc.rule_family) from exc
        return parse_skill_document(text, source)

    def _resolve(self, name: str) -> _SkillRecord:
        try:
            return self._records[name]
        except (KeyError, TypeError) as exc:
            raise UnknownSkillError(name) from exc


def parse_skill_document(
    text: str,
    source: SkillSource,
) -> SkillInstructions:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---\n"):
        raise InvalidSkillError("missing_frontmatter")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise InvalidSkillError("unterminated_frontmatter")
    try:
        metadata = yaml.safe_load(text[4:marker])
    except yaml.YAMLError as exc:
        raise InvalidSkillError("invalid_yaml") from exc
    if not isinstance(metadata, dict):
        raise InvalidSkillError("frontmatter_must_be_mapping")
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not name.strip():
        raise InvalidSkillError("invalid_skill_name")
    if not isinstance(description, str) or not description.strip():
        raise InvalidSkillError("invalid_skill_description")
    return SkillInstructions(
        name=name.strip(),
        description=description.strip(),
        body=text[marker + 5 :],
        source=source,
    )
