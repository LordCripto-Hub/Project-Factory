#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "experiments" / "memory-gate-b"))

from comparison.contracts import load_cases
from comparison.scoring import canonical_score_receipt, score_result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--case-alias", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = {case.alias: case for case in load_cases(args.cases)}
    if args.case_alias not in cases:
        raise SystemExit("unknown_case_alias")
    result = json.loads(args.input.read_text(encoding="utf-8-sig"))
    receipt = score_result(cases[args.case_alias], result)
    args.output.write_bytes(canonical_score_receipt(receipt))


if __name__ == "__main__":
    main()
