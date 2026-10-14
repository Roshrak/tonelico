"""Linux namespace must expose the mirror and one credential, not host files."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from linux_agy_boundary import linux_agy_command


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux namespace test")
class LinuxAgyBoundaryTest(unittest.TestCase):
    def test_disposable_guest_sees_only_mirror_and_its_own_keyring(self) -> None:
        with tempfile.TemporaryDirectory(prefix="softfac-boundary-test-") as raw:
            root = Path(raw)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "allowed.txt").write_text("visible", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("must be hidden", encoding="utf-8")
            fake = root / "fake-agy"
            fake.write_text(
                f"#!{Path(sys.executable).resolve()}\n"
                "import json, os, pathlib, subprocess\n"
                "item = subprocess.run(['secret-tool','lookup','service','gemini','username','antigravity'], capture_output=True)\n"
                "print(json.dumps({"
                "'cwd': os.getcwd(),"
                "'mirror': pathlib.Path('/workspace/allowed.txt').read_text(),"
                f"'outside_visible': pathlib.Path({str(outside)!r}).exists(),"
                "'host_bus_visible': pathlib.Path('/run/user/1000/bus').exists(),"
                "'credential': item.returncode == 0 and b'TEST_ACCESS_TOKEN' in item.stdout,"
                "'no_python_bytecode': os.environ.get('PYTHONDONTWRITEBYTECODE') == '1',"
                "'pytest_cache_outside_workspace': os.environ.get('PYTEST_ADDOPTS') == '-o cache_dir=/tmp/pytest-cache'"
                "}))\n",
                encoding="utf-8",
            )
            fake.chmod(0o700)
            token = json.dumps({"token": {"access_token": "TEST_ACCESS_TOKEN"}}).encode()
            with patch("linux_agy_boundary._approved_oauth_token", return_value=token):
                with linux_agy_command(workspace, fake, []) as (command, environment):
                    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["cwd"], "/workspace")
            self.assertEqual(report["mirror"], "visible")
            self.assertTrue(report["credential"])
            self.assertFalse(report["outside_visible"])
            self.assertFalse(report["host_bus_visible"])
            self.assertTrue(report["no_python_bytecode"])
            self.assertTrue(report["pytest_cache_outside_workspace"])


if __name__ == "__main__":
    unittest.main()
