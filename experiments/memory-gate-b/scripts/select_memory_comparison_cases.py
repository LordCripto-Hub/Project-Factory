from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EXPERIMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT / "src"))

from memory_bench.history_fixture import load_history_fixture


CLASS_SPECS = (
    (
        "exact",
        "exact_constraint",
        "report_exact_commit_subject",
        ("baseline", "memory"),
        ("git_show_subject",),
    ),
    (
        "temporal",
        "temporal_continuation",
        "continue_from_latest_change",
        ("memory", "baseline"),
        ("git_log_path_latest",),
    ),
    (
        "contradiction",
        "contradiction_prevention",
        "reject_superseded_change",
        ("baseline", "memory"),
        ("git_log_path_latest", "git_show_superseded_edge"),
    ),
)


def select_cases(dataset: Path, lock: Path) -> dict[str, object]:
    loaded = load_history_fixture(dataset, lock)
    events = {event.event_id: event for event in loaded.fixture.events}
    questions = sorted(loaded.fixture.questions, key=lambda row: row.question_id)
    cases: list[dict[str, object]] = []
    for family, case_class, decision, live_order, commands in CLASS_SPECS:
        candidates = [question for question in questions if question.family == family]
        if len(candidates) < 2:
            raise ValueError(f"dataset has fewer than two {family} cases")
        for index, question in enumerate(candidates[:2], start=1):
            allowed = list(question.relevant_event_ids)
            rejected: list[str] = []
            if family in {"temporal", "contradiction"}:
                current = events[allowed[0]]
                if not current.supersedes:
                    raise ValueError(f"{question.question_id} has no superseded evidence")
                rejected.append(current.supersedes)
            cases.append(
                {
                    "alias": f"cmp-{case_class.split('_', 1)[0]}-{index:02d}",
                    "question_id": question.question_id,
                    "class": case_class,
                    "live": index == 1,
                    "arm_order": list(live_order) if index == 1 else [],
                    "required_decision_id": decision,
                    "allowed_evidence_ids": allowed,
                    "rejected_evidence_ids": rejected,
                    "verification_command_ids": list(commands),
                }
            )
    return {
        "schema_version": 1,
        "dataset": {
            "directory": loaded.dataset_name,
            "source_sha": loaded.source_sha,
        },
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Select deterministic Gate B cases.")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    document = select_cases(args.dataset, args.lock)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
