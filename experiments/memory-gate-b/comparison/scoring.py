from __future__ import annotations

import json
from typing import Any, Iterable

from .contracts import ComparisonCase


RESULT_FIELDS = {
    "decision_id",
    "selected_evidence_ids",
    "rejected_evidence_ids",
    "commands",
    "conclusion",
}
COMMAND_FIELDS = {"command_id", "exit_code"}


class ComparisonResultError(ValueError):
    """Raised when a worker result is not the closed comparison envelope."""


def _identifier_list(result: dict[str, Any], key: str) -> list[str]:
    value = result.get(key)
    if not isinstance(value, list):
        raise ComparisonResultError(f"{key} must be a list")
    if not all(isinstance(item, str) and item for item in value):
        raise ComparisonResultError(f"{key} contains an invalid identifier")
    if len(set(value)) != len(value):
        raise ComparisonResultError(f"{key} contains duplicates")
    return list(value)


def validate_result_envelope(
    case: ComparisonCase,
    result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
        raise ComparisonResultError("worker result fields do not match the closed schema")
    decision = result.get("decision_id")
    conclusion = result.get("conclusion")
    if not isinstance(decision, str) or not decision:
        raise ComparisonResultError("decision_id must be a non-empty string")
    if not isinstance(conclusion, str) or not conclusion or len(conclusion) > 500:
        raise ComparisonResultError("conclusion must contain 1 to 500 characters")

    selected = _identifier_list(result, "selected_evidence_ids")
    rejected = _identifier_list(result, "rejected_evidence_ids")
    if set(selected) & set(rejected):
        raise ComparisonResultError("selected and rejected evidence overlap")

    commands = result.get("commands")
    if not isinstance(commands, list) or not commands:
        raise ComparisonResultError("commands must be a non-empty list")
    normalized_commands: list[dict[str, Any]] = []
    seen_commands: set[str] = set()
    for command in commands:
        if not isinstance(command, dict) or set(command) != COMMAND_FIELDS:
            raise ComparisonResultError("command fields do not match the closed schema")
        command_id = command.get("command_id")
        exit_code = command.get("exit_code")
        if not isinstance(command_id, str) or not command_id:
            raise ComparisonResultError("command_id must be a non-empty string")
        if command_id not in case.verification_command_ids:
            raise ComparisonResultError(f"unapproved command identifier: {command_id}")
        if command_id in seen_commands:
            raise ComparisonResultError(f"duplicate command identifier: {command_id}")
        if type(exit_code) is not int:
            raise ComparisonResultError("exit_code must be an integer")
        seen_commands.add(command_id)
        normalized_commands.append({"command_id": command_id, "exit_code": exit_code})

    return {
        "decision_id": decision,
        "selected_evidence_ids": selected,
        "rejected_evidence_ids": rejected,
        "commands": normalized_commands,
        "conclusion": conclusion,
    }


def score_result(
    case: ComparisonCase,
    result: dict[str, Any],
    *,
    violations: Iterable[str] = (),
) -> dict[str, Any]:
    normalized = validate_result_envelope(case, result)
    violation_ids = tuple(sorted(set(violations)))
    known_evidence = set(case.allowed_evidence_ids + case.rejected_evidence_ids)
    reported_evidence = set(normalized["selected_evidence_ids"] + normalized["rejected_evidence_ids"])
    selected = set(normalized["selected_evidence_ids"])
    rejected = set(normalized["rejected_evidence_ids"])
    harmful = bool(
        violation_ids
        or not reported_evidence.issubset(known_evidence)
        or selected & set(case.rejected_evidence_ids)
    )

    components = {
        "correctness": 40 if normalized["decision_id"] == case.required_decision_id else 0,
        "provenance": 25 if selected == set(case.allowed_evidence_ids) else 0,
        "verification": 20
        if {
            command["command_id"]
            for command in normalized["commands"]
            if command["exit_code"] == 0
        }
        == set(case.verification_command_ids)
        else 0,
        "contradiction_avoidance": 10
        if not (selected & set(case.rejected_evidence_ids))
        and set(case.rejected_evidence_ids).issubset(rejected)
        else 0,
        "discipline": 5,
    }
    score = 0 if harmful else sum(components.values())
    return {
        "schema_version": 1,
        "case_alias": case.alias,
        "components": components,
        "score": score,
        "successful": score >= 80 and not harmful,
        "harmful": harmful,
        "violations": list(violation_ids),
    }


def canonical_score_receipt(receipt: dict[str, Any]) -> bytes:
    return (json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
