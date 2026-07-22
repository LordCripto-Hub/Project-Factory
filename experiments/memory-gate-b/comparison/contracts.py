from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable


ALLOWED_CLASSES = {
    "exact_constraint": "exact",
    "temporal_continuation": "temporal",
    "contradiction_prevention": "contradiction",
}
ALLOWED_ARMS = {"baseline", "memory"}


class ComparisonFixtureError(ValueError):
    """Raised when the committed comparison fixture is unsafe or inconsistent."""


@dataclass(frozen=True)
class ComparisonCase:
    alias: str
    question_id: str
    case_class: str
    live: bool
    arm_order: tuple[str, ...]
    required_decision_id: str
    allowed_evidence_ids: tuple[str, ...]
    rejected_evidence_ids: tuple[str, ...]
    verification_command_ids: tuple[str, ...]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ComparisonFixtureError(f"cannot read comparison JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise ComparisonFixtureError(f"comparison JSON is not an object: {path.name}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ComparisonFixtureError(f"cannot read dataset JSONL: {path.name}") from error
    if not all(isinstance(row, dict) for row in rows):
        raise ComparisonFixtureError(f"dataset JSONL has a non-object: {path.name}")
    return rows


def _strings(row: dict[str, Any], key: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    value = row.get(key)
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ComparisonFixtureError(f"{key} must be a {'possibly empty ' if allow_empty else ''}list")
    result = tuple(value)
    if not all(isinstance(item, str) and item for item in result):
        raise ComparisonFixtureError(f"{key} contains an invalid identifier")
    if len(set(result)) != len(result):
        raise ComparisonFixtureError(f"{key} contains duplicates")
    return result


def validate_case(
    row: dict[str, Any],
    questions: dict[str, dict[str, Any]],
    event_ids: set[str],
) -> ComparisonCase:
    alias = row.get("alias")
    question_id = row.get("question_id")
    case_class = row.get("class")
    live = row.get("live")
    decision = row.get("required_decision_id")
    if not all(isinstance(value, str) and value for value in (alias, question_id, decision)):
        raise ComparisonFixtureError("case identifiers must be non-empty strings")
    if case_class not in ALLOWED_CLASSES:
        raise ComparisonFixtureError(f"unknown comparison class: {case_class}")
    if type(live) is not bool:
        raise ComparisonFixtureError("live must be a boolean")
    question = questions.get(question_id)
    if question is None:
        raise ComparisonFixtureError(f"unknown dataset question: {question_id}")
    if question.get("family") != ALLOWED_CLASSES[case_class]:
        raise ComparisonFixtureError(f"case class does not match dataset family: {alias}")

    arm_order = _strings(row, "arm_order", allow_empty=not live)
    if live:
        if len(arm_order) != 2 or set(arm_order) != ALLOWED_ARMS:
            raise ComparisonFixtureError(f"live case has invalid arm order: {alias}")
    elif arm_order:
        raise ComparisonFixtureError(f"offline-only case cannot define arm order: {alias}")

    allowed = _strings(row, "allowed_evidence_ids")
    rejected = _strings(row, "rejected_evidence_ids", allow_empty=True)
    commands = _strings(row, "verification_command_ids")
    if set(allowed) != set(question.get("relevant_event_ids", ())):
        raise ComparisonFixtureError(f"allowed evidence does not match gold question: {alias}")
    if set(allowed) & set(rejected):
        raise ComparisonFixtureError(f"allowed and rejected evidence overlap: {alias}")
    if not set(allowed + rejected).issubset(event_ids):
        raise ComparisonFixtureError(f"case references an unknown event: {alias}")

    return ComparisonCase(
        alias=alias,
        question_id=question_id,
        case_class=case_class,
        live=live,
        arm_order=arm_order,
        required_decision_id=decision,
        allowed_evidence_ids=allowed,
        rejected_evidence_ids=rejected,
        verification_command_ids=commands,
    )


def load_cases(path: str | Path, dataset_root: str | Path) -> tuple[ComparisonCase, ...]:
    document = _read_json(Path(path))
    dataset = Path(dataset_root)
    manifest = _read_json(dataset / "manifest.json")
    identity = document.get("dataset")
    if document.get("schema_version") != 1 or not isinstance(identity, dict):
        raise ComparisonFixtureError("unsupported comparison fixture schema")
    if identity.get("directory") != dataset.name:
        raise ComparisonFixtureError("comparison dataset directory mismatch")
    if identity.get("source_sha") != manifest.get("source_sha"):
        raise ComparisonFixtureError("comparison dataset source SHA mismatch")

    question_rows = _read_jsonl(dataset / "questions.jsonl")
    event_rows = _read_jsonl(dataset / "events.jsonl")
    questions = {str(row.get("question_id")): row for row in question_rows}
    event_ids = {str(row.get("event_id")) for row in event_rows}
    rows = document.get("cases")
    if not isinstance(rows, list) or len(rows) != 6 or not all(isinstance(row, dict) for row in rows):
        raise ComparisonFixtureError("comparison fixture must contain six case objects")
    cases = tuple(validate_case(row, questions, event_ids) for row in rows)
    aliases = [case.alias for case in cases]
    question_ids = [case.question_id for case in cases]
    if len(set(aliases)) != len(aliases):
        raise ComparisonFixtureError("duplicate comparison alias")
    if len(set(question_ids)) != len(question_ids):
        raise ComparisonFixtureError("duplicate comparison question")
    if sum(case.live for case in cases) != 3:
        raise ComparisonFixtureError("comparison fixture must contain three live cases")
    return cases


def live_cases(cases: Iterable[ComparisonCase]) -> tuple[ComparisonCase, ...]:
    return tuple(case for case in cases if case.live)
