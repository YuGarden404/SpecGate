import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from specgate.actions import Action
from specgate.context import LegacyContextBuilder, SkillContextContributor
from specgate.policy import WorkspacePolicy
from specgate.run_state import RunState
from specgate.skill_registry import SkillRegistry, SkillSession
from specgate.skill_tools import (
    LoadSkillArgs,
    LoadSkillHandler,
    LoadSkillResult,
    ReadSkillResourceArgs,
    ReadSkillResourceHandler,
    ReadSkillResourceResult,
)
from specgate.tool_handlers import ToolExecutionContext
from specgate.tool_registry import (
    PermissionClass,
    SideEffectClass,
    default_tool_registry,
)
from specgate.tool_runtime import ToolRuntime


def _write_demo_skill(root: Path) -> None:
    skill = root / "demo"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: demo\n"
        "description: Demonstrate progressive disclosure.\n"
        "---\n"
        "Follow the private demo instructions.\n",
        encoding="utf-8",
    )
    (skill / "references" / "guide.md").write_text(
        "RESOURCE_SENTINEL",
        encoding="utf-8",
    )


class SkillToolModelTests(unittest.TestCase):
    def test_models_reject_extra_fields(self):
        with self.assertRaises(ValidationError):
            LoadSkillArgs.model_validate({"name": "demo", "extra": True})
        with self.assertRaises(ValidationError):
            ReadSkillResourceArgs.model_validate(
                {"name": "demo", "path": "guide.md", "extra": True}
            )

    def test_result_models_expose_only_declared_skill_data(self):
        self.assertEqual(
            LoadSkillResult(name="demo", instructions="body").model_dump(),
            {"name": "demo", "instructions": "body"},
        )
        self.assertEqual(
            ReadSkillResourceResult(
                name="demo",
                path="references/guide.md",
                content="guide",
            ).model_dump(),
            {
                "name": "demo",
                "path": "references/guide.md",
                "content": "guide",
            },
        )


class SkillToolRegistrationTests(unittest.TestCase):
    def test_skill_tools_are_registered_only_when_explicitly_enabled(self):
        default_registry = default_tool_registry()
        enabled_registry = default_tool_registry(include_skill_tools=True)

        self.assertNotIn("load_skill", default_registry)
        self.assertNotIn("read_skill_resource", default_registry)
        self.assertEqual(
            tuple(definition.name for definition in enabled_registry.values())[-2:],
            ("load_skill", "read_skill_resource"),
        )
        load = enabled_registry.resolve("load_skill")
        read = enabled_registry.resolve("read_skill_resource")
        self.assertIsInstance(load.handler, LoadSkillHandler)
        self.assertIsInstance(read.handler, ReadSkillResourceHandler)
        self.assertEqual(load.permission_class, PermissionClass.READ)
        self.assertEqual(read.permission_class, PermissionClass.READ)
        self.assertEqual(load.side_effect_class, SideEffectClass.NONE)
        self.assertEqual(read.side_effect_class, SideEffectClass.NONE)


class SkillToolExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        _write_demo_skill(self.root)
        self.registry = SkillRegistry(workspace_roots=(self.root,))
        self.session = SkillSession(agent_run_id="run-1")
        self.policy = WorkspacePolicy(
            self.root,
            {"load_skill", "read_skill_resource"},
            set(),
            set(),
        )
        self.context = ToolExecutionContext(
            self.policy,
            None,
            skill_registry=self.registry,
            skill_session=self.session,
        )
        self.runtime = ToolRuntime(default_tool_registry(include_skill_tools=True))

    def tearDown(self):
        self.temporary.cleanup()

    def _execute(self, action: str, args: dict):
        preparation = self.runtime.prepare(Action("1", action, args))
        self.assertIsNone(preparation.failure)
        self.assertIsNotNone(preparation.call)
        return self.runtime.execute_prepared(preparation.call, self.context)

    def test_load_skill_returns_instructions_and_activates_only_that_session(self):
        other = SkillSession(agent_run_id="run-2")

        result = self._execute("load_skill", {"name": "demo"})

        self.assertTrue(result.ok)
        self.assertEqual(result.data["name"], "demo")
        self.assertIn("private demo instructions", result.data["instructions"])
        self.assertEqual(self.session.active_names, ("demo",))
        self.assertEqual(other.active_names, ())

    def test_read_resource_requires_an_active_skill(self):
        result = self._execute(
            "read_skill_resource",
            {"name": "demo", "path": "references/guide.md"},
        )

        self.assertFalse(result.ok)
        self.assertTrue(result.blocked)
        self.assertEqual(result.code, "inactive_skill")
        self.assertNotIn("RESOURCE_SENTINEL", str(result.data))

    def test_read_resource_returns_content_only_after_explicit_read(self):
        loaded = self._execute("load_skill", {"name": "demo"})
        self.assertNotIn("RESOURCE_SENTINEL", str(loaded.data))

        resource = self._execute(
            "read_skill_resource",
            {"name": "demo", "path": "references/guide.md"},
        )

        self.assertTrue(resource.ok)
        self.assertEqual(resource.data["name"], "demo")
        self.assertEqual(resource.data["path"], "references/guide.md")
        self.assertEqual(resource.data["content"], "RESOURCE_SENTINEL")

    def test_skill_tools_fail_closed_without_injected_runtime(self):
        context = ToolExecutionContext(self.policy, None)
        preparation = self.runtime.prepare(
            Action("1", "load_skill", {"name": "demo"})
        )
        self.assertIsNotNone(preparation.call)

        result = self.runtime.execute_prepared(preparation.call, context)

        self.assertFalse(result.ok)
        self.assertTrue(result.blocked)
        self.assertEqual(result.code, "skill_runtime_unavailable")

    def test_skill_tools_do_not_expand_capabilities_or_workspace_policy(self):
        capabilities = frozenset(self.policy.allowed_actions)
        allowed_actions = set(self.policy.allowed_actions)
        allowed_reads = set(self.policy.allowed_read_paths)
        allowed_writes = set(self.policy.allowed_write_paths)

        self.assertTrue(self._execute("load_skill", {"name": "demo"}).ok)
        self.assertTrue(
            self._execute(
                "read_skill_resource",
                {"name": "demo", "path": "references/guide.md"},
            ).ok
        )

        self.assertEqual(capabilities, frozenset(self.policy.allowed_actions))
        self.assertEqual(allowed_actions, self.policy.allowed_actions)
        self.assertEqual(allowed_reads, self.policy.allowed_read_paths)
        self.assertEqual(allowed_writes, self.policy.allowed_write_paths)


class SkillContextDisclosureTests(unittest.TestCase):
    def test_context_discloses_catalog_then_loaded_instructions_but_not_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_demo_skill(root)
            (root / "TASK_SPEC.md").write_text("# Task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- Verify", encoding="utf-8")
            registry = SkillRegistry(workspace_roots=(root,))
            session = SkillSession(agent_run_id="run-1")
            policy = WorkspacePolicy(
                root,
                {"load_skill", "read_skill_resource"},
                {"TASK_SPEC.md", "CHECKLIST.md"},
                set(),
            )
            builder = LegacyContextBuilder(
                root=root,
                strategy="baseline",
                policy=policy,
                context_contributors=(SkillContextContributor(registry, session),),
            )
            state = RunState("run-1")

            initial = builder.build(state).text
            LoadSkillHandler().execute(
                LoadSkillArgs(name="demo"),
                ToolExecutionContext(
                    policy,
                    None,
                    skill_registry=registry,
                    skill_session=session,
                ),
            )
            loaded = builder.build(state).text

        self.assertIn("Demonstrate progressive disclosure", initial)
        self.assertNotIn("private demo instructions", initial)
        self.assertNotIn("RESOURCE_SENTINEL", initial)
        self.assertIn("private demo instructions", loaded)
        self.assertNotIn("RESOURCE_SENTINEL", loaded)

    def test_skill_context_rejects_a_session_from_another_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_demo_skill(root)
            contributor = SkillContextContributor(
                SkillRegistry(workspace_roots=(root,)),
                SkillSession(agent_run_id="run-2"),
            )

            with self.assertRaises(ValueError):
                contributor.render(RunState("run-1"))


if __name__ == "__main__":
    unittest.main()
