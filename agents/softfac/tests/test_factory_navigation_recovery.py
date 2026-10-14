"""Deterministic navigation/capsule tests for AGY recovery."""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from hermes_factory_v2 import (  # noqa: E402
    AgyBuilder,
    BuilderProcessError,
    FactoryError,
    FactoryEngine,
    create_python_capsule,
    locate_python_symbol,
    reintegrate_python_capsule,
    validate_python_capsule_output,
)


class PythonCapsuleTests(unittest.TestCase):
    def capsule(self, source: str, *, symbol: str | None = None, line: int | None = None):
        return create_python_capsule(
            source,
            source_path="lib/large_module.py",
            base_commit="a" * 40,
            candidate_baseline_sha256="b" * 64,
            task_id="T1",
            attempt=2,
            symbol=symbol,
            line=line,
        )

    def test_locates_module_async_and_class_method_symbols(self):
        source = (
            "def module_fn(value):\n"
            "    return value\n\n"
            "async def async_fn(value):\n"
            "    return value\n\n"
            "class Worker:\n"
            "    def method(self):\n"
            "        return 1\n\n"
            "    async def async_method(self):\n"
            "        return 2\n"
        )
        self.assertEqual(locate_python_symbol(source, symbol="module_fn")["node_kind"], "FunctionDef")
        self.assertEqual(locate_python_symbol(source, symbol="async_fn")["node_kind"], "AsyncFunctionDef")
        self.assertEqual(
            locate_python_symbol(source, symbol="Worker.method")["qualified_symbol"],
            "Worker.method",
        )
        self.assertEqual(
            locate_python_symbol(source, line=11)["qualified_symbol"],
            "Worker.async_method",
        )

    def test_ambiguous_unqualified_symbol_is_rejected(self):
        source = "class A:\n    def run(self):\n        return 1\n\nclass B:\n    def run(self):\n        return 2\n"
        with self.assertRaisesRegex(FactoryError, "not unique"):
            locate_python_symbol(source, symbol="run")
        self.assertEqual(locate_python_symbol(source, symbol="B.run")["qualified_symbol"], "B.run")

    def test_capsule_is_physically_reduced_and_contains_no_original_file(self):
        source = "\n".join(["# padding"] * 40) + "\n\ndef target():\n    return 1\n"
        capsule = self.capsule(source, symbol="target")
        self.assertEqual(capsule["editable_file"], "target.py")
        self.assertLess(len(capsule["capsule_source"].encode("utf-8")), len(source.encode("utf-8")))
        self.assertNotIn("# padding", capsule["capsule_source"])
        self.assertNotIn("source", capsule["capsule_source"])

    def test_module_function_reintegration_uses_exact_hash_bound_range(self):
        source = "def target():\n    return 1\n\nvalue = 3\n"
        capsule = self.capsule(source, symbol="target")
        output = capsule["capsule_source"].replace("return 1", "# repaired\n    return 2")
        updated = reintegrate_python_capsule(capsule, source, output)
        self.assertIn("def target():\n    # repaired\n    return 2", updated)
        self.assertIn("value = 3", updated)
        namespace: dict[str, object] = {}
        exec(compile(updated, "large_module.py", "exec"), namespace)
        self.assertEqual(namespace["target"](), 2)

    def test_class_method_wrapper_preserves_multiline_string_content(self):
        source = (
            "class Worker:\n"
            "    def render(self):\n"
            "        message = \"\"\"\n"
            "        keep this indentation\n"
            "        \"\"\"\n"
            "        return message\n"
        )
        capsule = self.capsule(source, symbol="Worker.render")
        output = capsule["capsule_source"].replace("return message", "# repaired\n        return message")
        updated = reintegrate_python_capsule(capsule, source, output)
        namespace: dict[str, object] = {}
        exec(compile(updated, "large_module.py", "exec"), namespace)
        self.assertEqual(namespace["Worker"]().render(), "\n        keep this indentation\n        ")

    def test_duplicate_old_text_does_not_trigger_global_replacement(self):
        source = (
            "def first():\n"
            "    return 1\n\n"
            "def second():\n"
            "    return 1\n"
        )
        capsule = self.capsule(source, symbol="second")
        output = capsule["capsule_source"].replace("return 1", "return 2")
        updated = reintegrate_python_capsule(capsule, source, output)
        namespace: dict[str, object] = {}
        exec(compile(updated, "large_module.py", "exec"), namespace)
        self.assertEqual(namespace["first"](), 1)
        self.assertEqual(namespace["second"](), 2)

    def test_stale_source_and_old_block_fail_closed(self):
        source = "def target():\n    return 1\n"
        capsule = self.capsule(source, symbol="target")
        output = capsule["capsule_source"].replace("return 1", "return 2")
        with self.assertRaisesRegex(FactoryError, "source hash is stale"):
            reintegrate_python_capsule(capsule, source + "\n", output)
        stale_block = dict(capsule)
        stale_block["old_block_sha256"] = "c" * 64
        with self.assertRaisesRegex(FactoryError, "old block hash is stale"):
            reintegrate_python_capsule(stale_block, source, output)

    def test_extra_import_or_top_level_node_is_rejected(self):
        source = "def target():\n    return 1\n"
        capsule = self.capsule(source, symbol="target")
        with self.assertRaisesRegex(FactoryError, "exactly one function"):
            validate_python_capsule_output(capsule, "import os\n" + capsule["capsule_source"])

    def test_line_hint_binds_to_current_source_not_stale_line_numbers(self):
        source = "# header\n\ndef target():\n    return 1\n"
        capsule = self.capsule(source, line=4)
        self.assertEqual(capsule["qualified_symbol"], "target")
        self.assertEqual(
            capsule["source_sha256"],
            __import__("hashlib").sha256(source.encode("utf-8")).hexdigest(),
        )

    def test_visible_file_copy_excludes_the_large_unrelated_surface(self):
        with tempfile.TemporaryDirectory(prefix="capsule-copy-") as raw:
            source = Path(raw) / "source"
            mirror = Path(raw) / "mirror"
            source.mkdir()
            (source / "large.py").write_bytes(b"x" * 100_000)
            (source / "unrelated.py").write_text("value = 1\n", encoding="utf-8")
            from hermes_factory_v2 import AgyBuilder

            AgyBuilder._copy_sandbox_candidate(source, mirror, ["large.py"])
            self.assertTrue((mirror / "large.py").is_file())
            self.assertFalse((mirror / "unrelated.py").exists())

    def test_capsule_surface_rejects_any_extra_guest_path(self):
        before = {
            "target.py": {"kind": "file", "size": 10, "sha256": "a" * 64},
        }
        target_only = {
            "target.py": {"kind": "file", "size": 11, "sha256": "b" * 64},
        }
        AgyBuilder._validate_capsule_surface_delta(
            before,
            target_only,
            stdout_path=Path("stdout"),
            stderr_path=Path("stderr"),
        )
        for extra in (
            "tasks/todo.md",
            "__pycache__/target.cpython-313.pyc",
            "generated.py",
            "extra-directory",
            "unsafe-link",
        ):
            with self.subTest(extra=extra):
                after = dict(target_only)
                after[extra] = (
                    {"kind": "symlink", "target": "outside"}
                    if extra == "unsafe-link"
                    else {"kind": "directory"}
                    if extra == "extra-directory"
                    else {"kind": "file", "size": 1, "sha256": "c" * 64}
                )
                with self.assertRaises(BuilderProcessError) as context:
                    AgyBuilder._validate_capsule_surface_delta(
                        before,
                        after,
                        stdout_path=Path("stdout"),
                        stderr_path=Path("stderr"),
                    )
                self.assertEqual(context.exception.failure_code, "agy_isolation_failed")

    def test_line_hints_require_explicit_source_line_syntax(self):
        engine = FactoryEngine.__new__(FactoryEngine)
        for instruction in (
            "Scope:\n- lib/example.py\nImplementation steps:\n1. update behavior",
            "lib/example.py\nCriterion 7: preserve behavior",
        ):
            with self.subTest(instruction=instruction):
                self.assertIsNone(engine._navigation_line_hint(instruction, "lib/example.py"))
        for instruction in (
            "lib/example.py:123",
            "lib/example.py line 123",
            "lib/example.py (line 123)",
        ):
            with self.subTest(instruction=instruction):
                self.assertEqual(engine._navigation_line_hint(instruction, "lib/example.py"), 123)

    def test_recovery_compaction_preserves_authoritative_context(self):
        engine = FactoryEngine.__new__(FactoryEngine)
        instruction = (
            "Goal:\nOBJECTIVE-MUST-REMAIN\nTask contract: preserve the current behavior.\n\n"
            "Context:\n"
            + ("redundant navigation context\n" * 800)
            + "Target symbol: Worker.render\n\n"
            "Scope:\nAllowed files (hard boundary):\n- lib/example.py\n\n"
            "Failure evidence:\nLATEST-FAILURE-MUST-REMAIN\n"
        )
        packet = engine._shrink_builder_instruction(
            instruction,
            allowed_files=["lib/example.py"],
        )
        self.assertIn("OBJECTIVE-MUST-REMAIN", packet)
        self.assertIn("Task contract: preserve the current behavior.", packet)
        self.assertIn("lib/example.py", packet)
        self.assertIn("Worker.render", packet)
        self.assertIn("LATEST-FAILURE-MUST-REMAIN", packet)


if __name__ == "__main__":
    unittest.main(verbosity=2)
