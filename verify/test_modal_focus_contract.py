import re
import unittest
from pathlib import Path


HTML = (Path(__file__).parents[1] / "bin" / "todos.html").read_text()


class ModalFocusContract(unittest.TestCase):
    def test_details_are_collapsed_and_thread_stays_primary(self):
        self.assertIn('id="detailsToggle"', HTML)
        self.assertIn('aria-controls="detailsPanel"', HTML)
        self.assertIn('id="detailsPanel" class="details-panel" hidden', HTML)
        self.assertLess(HTML.index('id="detailsPanel"'), HTML.index('id="thread"'))

    def test_existing_edit_ids_and_delete_confirmation_remain(self):
        for field in ("editText", "doneCondition", "projectSlug", "contextQuestion", "stateSelect", "evidencePolicy", "saveDetails"):
            self.assertIn(f'id="{field}"', HTML)
        self.assertIn('id="confirmDelete"', HTML)
        self.assertIn("deleteConfirm.hidden=false", HTML)

    def test_keyboard_contract_is_present(self):
        self.assertIn("document.addEventListener('keydown',e=>{if(!openId||e.key!=='Tab')", HTML)
        self.assertIn("if(e.key==='Escape'&&openId)closeModal()", HTML)
        self.assertRegex(HTML, r"modalObserver\.observe\(document\.body")


if __name__ == "__main__":
    unittest.main()
