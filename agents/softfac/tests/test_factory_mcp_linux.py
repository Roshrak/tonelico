"""MCP adapter must use the current SoftFac configuration contract."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
sys.path.insert(0, str(ROOT / "lib"))
from factory_mcp_adapter import FactoryMcpServer


class FakeEngine:
    def __init__(self) -> None:
        self.config = None

    def plan(self, config):
        self.config = config
        return "test-run"

    def status(self, run_id):
        return {"run_id": run_id, "phase": "planned"}


class FactoryMcpLinuxTest(unittest.TestCase):
    def test_plan_accepts_comma_separated_files_with_current_config(self) -> None:
        engine = FakeEngine()
        server = FactoryMcpServer(engine)
        result = server.call_tool("factory_plan", {
            "repo": "/tmp/example", "request": "Fix example",
            "files": "src/app.py,tests/test_app.py", "test_cmd": "python -m unittest",
        })
        self.assertNotIn("isError", result)
        self.assertEqual(engine.config.requested_files, ["src/app.py", "tests/test_app.py"])
        self.assertEqual(engine.config.test_command, "python -m unittest")

    def test_health_tool_is_exposed_without_starting_a_run(self) -> None:
        names = {item["name"] for item in FactoryMcpServer(FakeEngine()).list_tools()}
        self.assertIn("factory_health", names)
        self.assertIn("factory_status", names)
        self.assertIn("factory_run", names)


if __name__ == "__main__":
    unittest.main()
