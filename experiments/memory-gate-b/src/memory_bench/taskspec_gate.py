from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from .history_fixture import LoadedHistoryFixture


RELEVANT_QUESTION_ID = "hist-exact-003"
IRRELEVANT_QUESTION = "zxqvplmokn 000000000000"
LOCAL_FIELDS = (
    "projectSlug",
    "profileRevision",
    "repository",
    "workingDirectory",
    "contextFiles",
    "verificationCommands",
    "allowedActions",
    "forbiddenActions",
    "evidencePolicy",
)


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _profile(server_url: str, enabled: bool) -> dict:
    return {
        "schemaVersion": 1,
        "revision": 1,
        "slug": "project-factory",
        "repository": "https://github.com/LordCripto-Hub/Project-Factory.git",
        "workingDirectory": "/workspace/project-factory",
        "allowedBranches": ["main"],
        "contextFiles": ["README.md", "AGENTS.md"],
        "verificationCommands": ["python3 -m unittest discover -s tests"],
        "allowedActions": ["read", "edit", "test"],
        "forbiddenActions": ["deploy", "push", "delete"],
        "limits": {
            "contextChars": 6000,
            "memoryTopK": 3,
            "memoryHops": 0,
            "memoryTimeoutSeconds": 8,
        },
        "memory": {
            "enabled": enabled,
            "serverUrl": server_url,
            "credentialRef": "env://MYPEOPLE_MEMORY_TOKEN",
        },
    }


def _task(task_id: str, question: str) -> dict:
    return {
        "id": task_id,
        "text": "Verify bounded Project Factory context",
        "doneCondition": "Gate B promotion checks pass",
        "projectSlug": "project-factory",
        "contextQuestion": question,
        "evidencePolicy": "required",
    }


def _case(task_spec) -> dict:
    serialized = _canonical_json(dict(task_spec))
    metadata = task_spec.memory_metadata
    return {
        "memory_status": task_spec["memoryStatus"],
        "claim_count": len(task_spec["memoryClaims"]),
        "claims": task_spec["memoryClaims"],
        "task_spec_chars": len(serialized),
        "estimated_tokens_formula": "ceil(canonical_json_characters/4)",
        "estimated_tokens": (len(serialized) + 3) // 4,
        "memory_metrics": metadata,
    }


def run_taskspec_gate(
    loaded: LoadedHistoryFixture,
    *,
    compiler: Callable,
    server_url: str,
    ledger_count: Callable[[], int],
    fixed_time: int,
) -> dict:
    question = next(
        item
        for item in loaded.fixture.questions
        if item.question_id == RELEVANT_QUESTION_ID
    )
    event_by_id = {
        event.event_id: event for event in loaded.fixture.events
    }
    clock = lambda: fixed_time
    before = ledger_count()
    baseline = compiler(
        _task("gate-b-relevant", question.query),
        _profile(server_url, False),
        now=clock,
    )
    relevant = compiler(
        _task("gate-b-relevant", question.query),
        _profile(server_url, True),
        now=clock,
    )
    after_relevant = ledger_count()
    irrelevant = compiler(
        _task("gate-b-irrelevant", IRRELEVANT_QUESTION),
        _profile(server_url, True),
        now=clock,
    )
    after_irrelevant = ledger_count()
    no_question = compiler(
        _task("gate-b-no-question", ""),
        _profile(server_url, True),
        now=clock,
    )
    after_no_question = ledger_count()

    produced_specs = (relevant, irrelevant, no_question)
    local_contract_preserved = all(
        baseline[field] == task_spec[field]
        for task_spec in produced_specs
        for field in LOCAL_FIELDS
    )
    relevant_ids = {
        claim["id"] for claim in relevant["memoryClaims"]
    }
    claims_grounded = all(
        claim["id"] in event_by_id
        and claim["projectSlug"] == "project-factory"
        and claim["sourceUri"] == event_by_id[claim["id"]].provenance
        for claim in relevant["memoryClaims"]
    )
    cases = {
        "baseline": _case(baseline),
        "relevant": _case(relevant),
        "irrelevant": _case(irrelevant),
        "no_question": _case(no_question),
    }
    result = {
        "schema_version": 1,
        "dataset": {
            "name": loaded.dataset_name,
            "repo_slug": loaded.repo_slug,
            "source_sha": loaded.source_sha,
        },
        "compiler_contract": {
            "module": "image://mypeople/bin/project_context.py",
            "gateway": "image://mypeople/memory-gateway/memory-gateway.mjs",
            "server_url": server_url,
            "top_k": 3,
            "hops": 0,
            "context_chars": 6000,
        },
        "cases": cases,
        "memory_delta": {
            "characters": (
                cases["relevant"]["task_spec_chars"]
                - cases["baseline"]["task_spec_chars"]
            ),
            "estimated_tokens": (
                cases["relevant"]["estimated_tokens"]
                - cases["baseline"]["estimated_tokens"]
            ),
        },
        "gateway_request_count": after_no_question - before,
        "actual_provider_tokens": "not_measured",
        "promotion_gates": {
            "relevant_single_recall": after_relevant - before == 1,
            "relevant_bounded_claims": 1 <= len(relevant["memoryClaims"]) <= 3,
            "relevant_gold_hit": bool(
                set(question.relevant_event_ids) & relevant_ids
            ),
            "relevant_grounded": claims_grounded,
            "irrelevant_single_recall": after_irrelevant - after_relevant == 1,
            "irrelevant_empty": irrelevant["memoryClaims"] == [],
            "no_question_no_recall": after_no_question == after_irrelevant,
            "no_question_status": no_question["memoryStatus"] == "not_requested",
            "local_contract_preserved": local_contract_preserved,
            "context_budget": all(
                item["task_spec_chars"] <= 6000 for item in cases.values()
            ),
            "provider_tokens_not_measured": all(
                item["memory_metrics"]["aiUsage"] == "not_measured"
                for item in cases.values()
            ),
        },
    }
    digest_source = _canonical_json(result).encode("utf-8")
    result["logical_digest"] = hashlib.sha256(digest_source).hexdigest()
    return result


def render_taskspec_report(result: dict) -> str:
    lines = [
        "# Gate B TaskSpec Memory Report",
        "",
        f"- Dataset: `{result['dataset']['name']}`",
        f"- Source SHA: `{result['dataset']['source_sha']}`",
        f"- Gateway recalls: {result['gateway_request_count']}",
        f"- Actual provider tokens: `{result['actual_provider_tokens']}`",
        (
            f"- Estimated memory delta: "
            f"{result['memory_delta']['characters']} characters / "
            f"{result['memory_delta']['estimated_tokens']} tokens"
        ),
        f"- Logical digest: `{result['logical_digest']}`",
        "",
        "## Cases",
        "",
    ]
    for name, case in result["cases"].items():
        lines.append(
            f"- {name}: status={case['memory_status']}, "
            f"claims={case['claim_count']}, chars={case['task_spec_chars']}"
        )
    lines.extend(["", "## Promotion Gates", ""])
    for name, passed in result["promotion_gates"].items():
        lines.append(f"- [{'x' if passed else ' '}] {name}")
    return "\n".join(lines) + "\n"


def write_taskspec_evidence(result: dict, output_dir: str | Path) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "taskspec-memory-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "taskspec-memory-report.md").write_text(
        render_taskspec_report(result),
        encoding="utf-8",
    )
