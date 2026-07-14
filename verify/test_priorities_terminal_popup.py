import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PrioritiesTerminalPopupTests(unittest.TestCase):
    def test_compact_owner_link_does_not_register_a_second_open_handler(self):
        html = (ROOT / "bin" / "todos.html").read_text(encoding="utf-8")

        self.assertIn(
            "x.href='/todo/terminal?agent='+encodeURIComponent(a)",
            html,
        )
        self.assertIn("x.target='_blank'", html)
        self.assertIn("x.rel='noopener'", html)
        self.assertNotIn("addEventListener('click',e=>openAgent", html)
        self.assertNotIn(
            "as.firstChild.onclick=e=>openAgent(t.assignee,e)",
            html,
        )

    def test_open_agent_does_not_stage_an_about_blank_popup(self):
        html = (ROOT / "bin" / "todos.html").read_text(encoding="utf-8")

        self.assertNotIn(
            "window.open('about:blank','_blank')",
            html,
        )


    def test_terminal_graph_uses_native_owner_links(self):
        html = (ROOT / "bin" / "terminal-graph.html").read_text(encoding="utf-8")

        self.assertIn("'/todo/terminal?agent='", html)
        self.assertIn("target='_blank'", html)
        self.assertIn("rel='noopener'", html)
        self.assertNotIn("window.open('about:blank','_blank')", html)
        self.assertNotIn("'/todo/attach?agent='", html)
    def test_local_attach_response_does_not_publish_a_remote_base(self):
        server = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")

        self.assertIn('base="" if h==HOST_ID else', server)


if __name__ == "__main__":
    unittest.main()
