#!/usr/bin/env python3
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")
BOARD = (ROOT / "bin" / "todos.html").read_text(encoding="utf-8")


class BossPublicationApprovalApiContract(unittest.TestCase):
    def test_projection_is_allow_listed_and_routes_are_present(self):
        self.assertIn("PUBLIC_APPROVAL_FIELDS", SERVER)
        self.assertIn('"/todo/publication-approvals"', SERVER)
        self.assertIn('"/todo/publication-approval"', SERVER)
        self.assertIn("ceo_approval_required", SERVER)
        self.assertIn('kind!="browser"', SERVER)
        self.assertIn("repositorySlug", SERVER)
        for secret in ("transactionNonce", "workspace", "password", "private_key", "token"):
            self.assertNotIn(f'"{secret}"', SERVER.split("publication_approval_projection", 1)[1].split("class Handler", 1)[0])

    def test_board_renders_approval_actions_without_raw_html(self):
        self.assertIn("publicationApprovals", BOARD)
        self.assertIn("CEO approval", BOARD)
        self.assertIn("Approve", BOARD)
        self.assertIn("Reject", BOARD)
        self.assertIn("textContent", BOARD)
        self.assertNotIn("innerHTML", BOARD)
        self.assertTrue(re.search(r"/todo/publication-approval", BOARD))


if __name__ == "__main__":
    unittest.main()
