#!/usr/bin/env python3
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BoardPollingContractTests(unittest.TestCase):
    def test_out_of_order_work_is_coalesced_and_never_overlaps(self):
        result = subprocess.run(
            ["node", str(ROOT / "verify" / "test_board_polling_contract.js")],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_board_uses_shared_coordinator(self):
        page = (ROOT / "bin" / "todos.html").read_text(encoding="utf-8")
        self.assertIn('/assets/board-polling.js', page)
        self.assertIn('createBoardPollCoordinator', page)
        self.assertNotIn('async function refresh(){try{const b=await api', page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
