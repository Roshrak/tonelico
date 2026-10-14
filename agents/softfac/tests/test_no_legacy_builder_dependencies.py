"""Acceptance checks for the active v1 production surface."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "lib" / "hermes_factory_v2.py"


class ActiveProductionSurfaceTests(unittest.TestCase):
    def test_active_module_has_no_legacy_builder_or_luna_dispatch(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(SOURCE))

        self.assertNotIn("class AiderBuilder", source)
        self.assertNotIn("LEGACY_AIDER", source)
        self.assertNotIn("clean_aider_generated_artifacts", source)
        self.assertNotIn("Sol Planner", source)
        self.assertNotIn("sol_plan.json", source)
        self.assertNotIn("--luna-", source)

        luna_calls = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_luna_repair"
        ]
        luna_roles = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.keyword)
            and node.arg == "role"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.value.value.lower().startswith("luna")
        ]
        self.assertEqual(luna_calls, [])
        self.assertEqual(luna_roles, [])

    def test_legacy_bridge_files_are_not_shipped(self) -> None:
        self.assertFalse((ROOT / "bridge" / "agy_bridge.py").exists())
        self.assertFalse((ROOT / "systemd" / "agy-bridge.service.example").exists())
        self.assertNotIn(".aider", (ROOT / ".gitignore").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
