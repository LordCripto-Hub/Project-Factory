#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

from memory_bench.history_fixture import load_history_fixture
from memory_bench.taskspec_gate import run_taskspec_gate, write_taskspec_evidence


PROJECT_CONTEXT_PATH = Path("/home/mp/mypeople/bin/project_context.py")
MEMORY_GATEWAY_PATH = Path(
    "/home/mp/mypeople/memory-gateway/memory-gateway.mjs"
)


def load_project_context(path: Path):
    spec = importlib.util.spec_from_file_location("project_context", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("project_context_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--lock", required=True)
    parser.add_argument("--project-context", required=True)
    parser.add_argument("--server-ready", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if os.environ.get("MYPEOPLE_MEMORY_ALLOW_HTTP") == "1":
        raise RuntimeError("http_override_forbidden")
    project_context_path = Path(args.project_context)
    if project_context_path != PROJECT_CONTEXT_PATH:
        raise RuntimeError("unexpected_project_context_path")
    if not MEMORY_GATEWAY_PATH.is_file():
        raise RuntimeError("memory_gateway_unavailable")
    ready = json.loads(Path(args.server_ready).read_text(encoding="utf-8"))
    if ready.get("url") != "https://127.0.0.1:18443/mcp":
        raise RuntimeError("unexpected_server_url")
    loaded = load_history_fixture(args.dataset, args.lock)
    project_context = load_project_context(project_context_path)
    ledger = Path(args.ledger)
    result = run_taskspec_gate(
        loaded,
        compiler=project_context.compile_task_spec,
        server_url=ready["url"],
        ledger_count=lambda: len(
            [line for line in ledger.read_text(encoding="utf-8").splitlines() if line]
        ),
        fixed_time=1784473171,
    )
    if not all(result["promotion_gates"].values()):
        raise RuntimeError("gate_b_promotion_failed")
    write_taskspec_evidence(result, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
