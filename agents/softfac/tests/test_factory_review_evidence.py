"""Sol receives bounded Runner output only after its recorded hash is verified."""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from hermes_factory_v2 import review_test_evidence_with_log_tail


class ReviewTestEvidenceTests(unittest.TestCase):
    def test_verified_log_shows_actual_test_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            log = run_dir / "test.log"
            content = b"Ran 1 test in 0.001s\n\nOK\n"
            log.write_bytes(content)
            result = review_test_evidence_with_log_tail(
                [{"log": str(log), "log_sha256": hashlib.sha256(content).hexdigest()}], run_dir
            )[0]
            self.assertEqual(result["observed_test_count"], 1)
            self.assertIn("OK", result["verified_log_tail"])

    def test_tampered_and_outside_logs_are_not_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "run"
            run_dir.mkdir()
            outside = root / "outside.log"
            outside.write_text("private text")
            inside = run_dir / "test.log"
            inside.write_text("changed text")
            expected = hashlib.sha256(b"original text").hexdigest()
            records = review_test_evidence_with_log_tail(
                [{"log": str(inside), "log_sha256": expected},
                 {"log": str(outside), "log_sha256": hashlib.sha256(outside.read_bytes()).hexdigest()}],
                run_dir,
            )
            self.assertTrue(all("verified_log_tail" not in item for item in records))


if __name__ == "__main__":
    unittest.main()
