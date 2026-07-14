#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_public_history", ROOT / "verify" / "audit_public_history.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class PublicHistoryContract(unittest.TestCase):
    def test_patterns_detect_constructed_sensitive_samples(self):
        samples = {
            "provider_token": b"token=" + b"tskey" + b"-auth-examplevalue1234567890",
            "email_address": b"operator" + b"@example.com",
            "private_windows_path": b"C:\\" + b"Users\\PrivateOperator\\project",
            "private_macos_path": b"/" + b"Users/PrivateOperator/project",
            "authorization_header": b"Authorization:" + b" Bearer examplevalue12345",
        }
        for label, sample in samples.items():
            self.assertIsNotNone(audit.PATTERNS[label].search(sample), label)

    def test_current_tree_has_no_sensitive_public_blob(self):
        self.assertEqual(audit.scan(tree_only=True), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
