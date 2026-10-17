import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from audit import RAW, audit


class AuditSmokeTest(unittest.TestCase):
    def test_source_schema_and_invariants(self):
        result = audit(RAW)
        self.assertEqual(result["rows"], 64000)
        self.assertEqual(result["columns"], 12)
        self.assertEqual(result["sha256"], "0e5893329d8b93cefecc571777672028290ab69865718020c78c7284f291aece")
        self.assertEqual(sum(x["count"] for x in result["groups"].values()), result["rows"])
        self.assertEqual(result["checks"]["history_segment_mismatch"], 0)


if __name__ == "__main__":
    unittest.main()
