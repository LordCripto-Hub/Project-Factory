#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys


EXPERIMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT))
sys.path.insert(0, str(EXPERIMENT / "src"))

from comparison.contracts import load_cases
from comparison.offline import canonical_receipt, run_offline_comparison
from memory_bench.history_fixture import load_history_fixture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--lock",
        default=str(EXPERIMENT / "docker" / "history-hybrid.dataset-lock.json"),
    )
    args = parser.parse_args()
    loaded = load_history_fixture(args.dataset, args.lock)
    cases = load_cases(args.cases, args.dataset)
    receipt = run_offline_comparison(
        loaded,
        cases,
        fixture_path=args.cases,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_receipt(receipt))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
