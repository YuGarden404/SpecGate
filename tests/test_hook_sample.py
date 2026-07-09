from pathlib import Path
import unittest


class HookSampleTests(unittest.TestCase):
    def test_pre_commit_sample_documents_expected_guardrails(self):
        hook = Path("hooks/pre-commit.sample")

        self.assertTrue(hook.exists())
        text = hook.read_text(encoding="utf-8")

        self.assertIn("SECRET_PATTERNS", text)
        self.assertIn("git grep --cached", text)
        self.assertIn("OPENAI_API_KEY", text)
        self.assertIn("GEMINI_API_KEY", text)
        self.assertIn("examples/knowledge_nav/TASK_SPEC.md", text)
        self.assertIn("examples/knowledge_nav/CHECKLIST.md", text)
        self.assertIn("examples/knowledge_nav/specgate.toml", text)
        self.assertIn("python -m unittest discover -s tests -v", text)
        self.assertIn("not part of the SpecGate runtime", text)
        self.assertIn("while IFS= read -r staged_file", text)
        self.assertIn('"$staged_file"', text)


if __name__ == "__main__":
    unittest.main()
