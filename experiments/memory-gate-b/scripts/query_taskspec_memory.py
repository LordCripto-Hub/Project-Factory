#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

from memory_bench.history_fixture import load_history_fixture
from memory_bench.taskspec_memory import PROJECT_SLUG, recall_history_claims


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--lock", required=True)
    args = parser.parse_args()
    request = json.load(sys.stdin)
    if not isinstance(request, dict) or set(request) != {
        "projectSlug",
        "query",
        "limit",
        "hops",
    }:
        raise ValueError("invalid_recall_request")
    if request["projectSlug"] != PROJECT_SLUG:
        raise ValueError("project_mismatch")
    if isinstance(request["hops"], bool) or request["hops"] != 0:
        raise ValueError("invalid_recall_hops")
    loaded = load_history_fixture(args.dataset, args.lock)
    result = {
        "claims": recall_history_claims(
            loaded,
            request["query"],
            limit=request["limit"],
        ),
        "aiUsage": "not_measured",
    }
    json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
