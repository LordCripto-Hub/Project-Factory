#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from local_memory_emergency import LocalEmergencyAdapter
from memory_recovery import recover
from memory_bench.history_fixture import load_history_fixture
from memory_bench.taskspec_memory import HistoryMemoryStore, PROJECT_SLUG


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--lock", required=True)
    parser.add_argument("--runtime", required=True)
    args = parser.parse_args()
    request = json.load(sys.stdin)
    if not isinstance(request, dict) or set(request) != {
        "projectSlug", "query", "limit", "hops"
    }:
        raise ValueError("invalid_recall_request")
    if request["projectSlug"] != PROJECT_SLUG:
        raise ValueError("project_mismatch")
    if isinstance(request["hops"], bool) or request["hops"] != 0:
        raise ValueError("invalid_recall_hops")
    limit = request["limit"]
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 3:
        raise ValueError("invalid_recall_limit")

    loaded = load_history_fixture(args.dataset, args.lock)
    store = HistoryMemoryStore(loaded)
    emergency = LocalEmergencyAdapter(args.dataset, args.lock, args.runtime)
    try:
        result = recover(request["query"], {
            "fast": store.fast,
            "deep": store.deep,
            "exhaustive": store.exhaustive,
            "emergency": lambda query, count: {
                key: value for key, value in emergency.retrieve(query, count).items()
                if key in {"claims", "examinedCount"}
            },
        })
    finally:
        store.close()
    result["aiUsage"] = "not_measured"
    json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
