from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest import mock

from specgate.skill_registry import (
    DuplicateSkillError,
    InvalidSkillError,
    SkillRegistry,
    SkillResourceError,
    SkillSession,
    SkillSource,
)
from specgate.workspace_fs import WorkspacePathError


def _write_skill(
    root: Path,
    directory: str,
    *,
    name: str = "demo",
    description: str = "Demonstrate a safe skill.",
    body: str = "Follow the safe workflow.\n",
) -> Path:
    skill_dir = root / directory
    skill_dir.mkdir(parents=True)
    document = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n"
        f"{body}"
    )
    (skill_dir / "SKILL.md").write_text(document, encoding="utf-8")
    return skill_dir


class SkillRegistryTests(unittest.TestCase):
    def test_catalog_exposes_only_name_description_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "demo")

            registry = SkillRegistry(builtin_roots=(root,))

            catalog = registry.catalog()
            self.assertEqual(len(catalog), 1)
            self.assertEqual(
                asdict(catalog[0]),
                {
                    "name": "demo",
                    "description": "Demonstrate a safe skill.",
                    "source": SkillSource.BUILTIN,
                },
            )
            self.assertNotIn("workflow", str(catalog[0]).lower())

    def test_load_reads_utf8_instructions_from_explicit_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "demo", body="Use UTF-8 instructions: 安全。\n")

            instructions = SkillRegistry(workspace_roots=(root,)).load("demo")

            self.assertEqual(instructions.name, "demo")
            self.assertEqual(instructions.description, "Demonstrate a safe skill.")
            self.assertEqual(instructions.body, "Use UTF-8 instructions: 安全。\n")
            self.assertEqual(instructions.source, SkillSource.WORKSPACE)

    def test_unconfigured_roots_are_not_scanned(self):
        with tempfile.TemporaryDirectory() as configured_tmp, tempfile.TemporaryDirectory() as other_tmp:
            configured = Path(configured_tmp)
            other = Path(other_tmp)
            _write_skill(configured, "visible", name="visible")
            _write_skill(other, "hidden", name="hidden")

            registry = SkillRegistry(workspace_roots=(configured,))

            self.assertEqual(
                tuple(entry.name for entry in registry.catalog()),
                ("visible",),
            )

    def test_duplicate_name_across_sources_fails_closed(self):
        with tempfile.TemporaryDirectory() as builtin_tmp, tempfile.TemporaryDirectory() as workspace_tmp:
            builtin = Path(builtin_tmp)
            workspace = Path(workspace_tmp)
            _write_skill(builtin, "first", name="duplicate")
            _write_skill(workspace, "second", name="duplicate")

            with self.assertRaises(DuplicateSkillError) as raised:
                SkillRegistry(
                    builtin_roots=(builtin,),
                    workspace_roots=(workspace,),
                )

            self.assertEqual(raised.exception.name, "duplicate")
            self.assertNotIn("Follow the safe workflow", str(raised.exception))

    def test_invalid_frontmatter_fails_with_stable_codes(self):
        cases = {
            "missing_frontmatter": "name: demo\n",
            "unterminated_frontmatter": "---\nname: demo\n",
            "invalid_yaml": "---\nname: [\n---\nbody\n",
            "frontmatter_must_be_mapping": "---\n- demo\n---\nbody\n",
            "invalid_skill_name": "---\ndescription: demo\n---\nbody\n",
            "invalid_skill_description": "---\nname: demo\n---\nbody\n",
        }
        for expected_code, document in cases.items():
            with self.subTest(expected_code=expected_code), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                skill_dir = root / "demo"
                skill_dir.mkdir()
                (skill_dir / "SKILL.md").write_text(document, encoding="utf-8")

                with self.assertRaises(InvalidSkillError) as raised:
                    SkillRegistry(workspace_roots=(root,))

                self.assertEqual(raised.exception.code, expected_code)

    def test_non_utf8_skill_document_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "demo"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_bytes(b"---\nname: \xff\n---\n")

            with self.assertRaises(InvalidSkillError) as raised:
                SkillRegistry(workspace_roots=(root,))

            self.assertEqual(raised.exception.code, "invalid_utf8")

    def test_resource_read_is_utf8_and_scoped_to_skill_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = _write_skill(root, "demo")
            references = skill_dir / "references"
            references.mkdir()
            (references / "guide.md").write_text("资源正文", encoding="utf-8")

            resource = SkillRegistry(workspace_roots=(root,)).read_resource(
                "demo",
                "references/guide.md",
            )

            self.assertEqual(resource.name, "demo")
            self.assertEqual(resource.path, "references/guide.md")
            self.assertEqual(resource.content, "资源正文")
            self.assertEqual(resource.source, SkillSource.WORKSPACE)

    def test_resource_escape_and_non_utf8_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = _write_skill(root, "demo")
            (root / "outside.txt").write_text("outside", encoding="utf-8")
            (skill_dir / "binary.dat").write_bytes(b"\xff\xfe")
            registry = SkillRegistry(workspace_roots=(root,))

            for path in ("../outside.txt", "/outside.txt", "C:/outside.txt"):
                with self.subTest(path=path), self.assertRaises(SkillResourceError) as raised:
                    registry.read_resource("demo", path)
                self.assertEqual(raised.exception.code, "path_escape")

            with self.assertRaises(SkillResourceError) as raised:
                registry.read_resource("demo", "binary.dat")
            self.assertEqual(raised.exception.code, "invalid_utf8")

    def test_linked_skill_document_and_resource_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(tmp)
            outside = Path(outside_tmp)
            external_document = outside / "SKILL.md"
            external_document.write_text(
                "---\nname: demo\ndescription: external\n---\nbody\n",
                encoding="utf-8",
            )
            skill_dir = root / "demo"
            skill_dir.mkdir()
            try:
                (skill_dir / "SKILL.md").symlink_to(external_document)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            with self.assertRaises(InvalidSkillError) as raised:
                SkillRegistry(workspace_roots=(root,))
            self.assertIn(raised.exception.code, {"linked_path", "reparse_point"})

    def test_linked_resource_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(tmp)
            outside = Path(outside_tmp)
            skill_dir = _write_skill(root, "demo")
            external = outside / "secret.txt"
            external.write_text("external", encoding="utf-8")
            registry = SkillRegistry(workspace_roots=(root,))
            try:
                (skill_dir / "linked.txt").symlink_to(external)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            with self.assertRaises(SkillResourceError) as raised:
                registry.read_resource("demo", "linked.txt")

            self.assertIn(raised.exception.code, {"linked_path", "reparse_point"})

    def test_reparse_root_scan_fails_closed_without_platform_privileges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch(
                "specgate.skill_registry.workspace_fs.iter_workspace_files",
                side_effect=WorkspacePathError("unsafe root", "reparse_point"),
            ):
                with self.assertRaises(InvalidSkillError) as raised:
                    SkillRegistry(workspace_roots=(root,))

            self.assertEqual(raised.exception.code, "reparse_point")

    def test_reparse_resource_fails_closed_without_platform_privileges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "demo")
            registry = SkillRegistry(workspace_roots=(root,))
            with mock.patch(
                "specgate.skill_registry.workspace_fs.read_workspace_text",
                side_effect=WorkspacePathError(
                    "unsafe resource",
                    "reparse_point",
                ),
            ):
                with self.assertRaises(SkillResourceError) as raised:
                    registry.read_resource("demo", "references/guide.md")

            self.assertEqual(raised.exception.code, "reparse_point")

    def test_sessions_are_isolated_per_agent_run(self):
        first = SkillSession(agent_run_id="agent-1")
        second = SkillSession(agent_run_id="agent-2")

        first.activate("demo")
        first.activate("demo")

        self.assertEqual(first.active_names, ("demo",))
        self.assertEqual(second.active_names, ())


if __name__ == "__main__":
    unittest.main()
