from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "docker" / "taskspec-memory-server.mjs"
COMPOSE = ROOT / "docker" / "compose.taskspec-memory.yml"
ENTRYPOINT = ROOT / "docker" / "taskspec-memory-entrypoint.sh"


class TaskSpecDockerContractTests(unittest.TestCase):
    def test_server_is_https_authenticated_and_recall_only(self):
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn("createHttpsServer({key, cert}, app)", source)
        self.assertIn("createHttpServer(app)", source)
        self.assertIn("MYPEOPLE_GATE_B_LIVE_CANARY", source)
        self.assertIn("127.0.0.1", source)
        self.assertIn("registerTool('recall'", source)
        self.assertIn("Bearer", source)
        self.assertIn("queryDigest", source)
        self.assertNotIn("registerTool('remember'", source)
        self.assertNotIn("registerTool('forget'", source)
        self.assertNotIn("console.log", source)

    def test_server_delegates_to_locked_python_bridge(self):
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn("/workspace/scripts/query_taskspec_memory.py", source)
        self.assertIn("/project-factory-history-039a62988625", source)
        self.assertIn("/workspace/docker/history-hybrid-039a62988625.dataset-lock.json", source)
        self.assertNotIn("exec(", source)
        self.assertIn("shell: false", source)

    def test_compose_is_no_network_read_only_and_credential_free(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        for contract in (
            "network_mode: none",
            "read_only: true",
            "user: mp",
            "init: true",
            "no-new-privileges:true",
            "cap_drop:",
            "- ALL",
            "pids_limit:",
            'MYPEOPLE_MEMORY_ALLOW_HTTP: "0"',
        ):
            self.assertIn(contract, compose)
        for forbidden in (
            "ports:",
            "/var/run/docker.sock",
            "mypeople-todos",
            "project-factory-history-preliminary",
            "TS_AUTHKEY",
        ):
            self.assertNotIn(forbidden, compose)
        for secret in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "CODEX_API_KEY",
            "GH_TOKEN",
            "GITHUB_TOKEN",
        ):
            self.assertIn(f'{secret}: ""', compose)

    def test_entrypoint_generates_ephemeral_tls_and_uses_image_owned_code(self):
        source = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn("openssl req -x509", source)
        self.assertIn("subjectAltName=IP:127.0.0.1", source)
        self.assertIn("/work/tls", source)
        self.assertIn("/home/mp/mypeople/bin/project_context.py", source)
        self.assertIn("/home/mp/mypeople/memory-gateway/memory-gateway.mjs", source)
        self.assertIn("/home/mp/mypeople/memory-gateway/node_modules", source)
        self.assertIn("trap cleanup EXIT", source)
        self.assertNotIn("MYPEOPLE_MEMORY_ALLOW_HTTP=1", source)
        self.assertNotIn("docker compose down -v", source)


if __name__ == "__main__":
    unittest.main()
