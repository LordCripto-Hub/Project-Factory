"""Synthetic provider/runtime adapter used only by comparison E2E tests."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import memory_comparison

CASES = [
    {"alias": "cmp-exact-01", "arm_order": ["baseline", "memory"]},
    {"alias": "cmp-temporal-01", "arm_order": ["memory", "baseline"]},
    {"alias": "cmp-contradiction-01", "arm_order": ["baseline", "memory"]},
]
CLEAN = {"worker_absent": True, "card_absent": True, "conversation_retired": True, "temp_artifacts_absent": True}

def _result(alias: str, arm: str, *, harmful: bool = False) -> dict:
    score = 0 if harmful else 100
    return {
        "score_receipt": {"schema_version": 1, "case_alias": alias, "components": {"correctness": 0 if harmful else 40, "provenance": 0 if harmful else 25, "verification": 0 if harmful else 20, "contradiction_avoidance": 0 if harmful else 10, "discipline": 0 if harmful else 5}, "score": score, "successful": not harmful, "harmful": harmful, "violations": ["synthetic_harm"] if harmful else []},
        "metrics": {"wall_time_ms": 25, "retrieval_latency_ms": 4 if arm == "memory" else "not_applicable", "memory_context_tokens_estimated": 24 if arm == "memory" else 0, "provider_tokens": "not_measured", "rework_count": 0},
    }

def _start(root: Path, run_id: str) -> None:
    memory_comparison.start_run(root, run_id=run_id, cases=CASES, fixture_sha256="a" * 64)
    memory_comparison.record_offline_qualification(root, run_id=run_id, logical_digest="b" * 64, passed=True)

def run_success_fixture(root: Path) -> dict:
    run_id = "synthetic-success"
    _start(root, run_id)
    schedule, workers, cards, conversations = [], [], [], []
    active_resources: set[str] = set()
    absence_checks, baseline_clean, memory_bounded = [], True, True
    for case in CASES:
        for arm in case["arm_order"]:
            serial = len(schedule) + 1
            worker, card, conversation = f"worker-{serial}", f"card-{serial}", f"conversation-{serial}"
            absence_checks.append(not active_resources)
            active_resources.update((worker, card, conversation))
            task_spec = {"task": card, "project": "project-factory"}
            if arm == "memory":
                task_spec["memory"] = {"blocks": [{"id": "bounded-1", "estimated_tokens": 24}]}
                memory_bounded &= set(task_spec["memory"]) == {"blocks"} and len(task_spec["memory"]["blocks"]) == 1
            else:
                baseline_clean &= "memory" not in task_spec
            artifact = root / f"artifact-{serial}.json"
            artifact.write_text(json.dumps(task_spec), encoding="utf-8")
            memory_comparison.start_arm(root, run_id=run_id, case_alias=case["alias"], arm=arm, worker_id=worker, card_id=card, conversation_id=conversation)
            memory_comparison.record_arm_result(root, run_id=run_id, case_alias=case["alias"], arm=arm, result=_result(case["alias"], arm))
            artifact.unlink()
            active_resources.clear()
            memory_comparison.record_cleanup(root, run_id=run_id, evidence=CLEAN)
            schedule.append([case["alias"], arm]); workers.append(worker); cards.append(card); conversations.append(conversation)
        memory_comparison.complete_pair(root, run_id=run_id, case_alias=case["alias"])
    memory_comparison.complete_run(root, run_id=run_id)
    summary = memory_comparison.build_public_summary(root, run_id)
    server = (ROOT / "bin" / "todo-server.py").read_text(encoding="utf-8")
    return {"schedule": schedule, "worker_ids": workers, "card_ids": cards, "conversation_ids": conversations, "first_absent_before_second": absence_checks[1:], "baseline_has_no_memory": baseline_clean, "memory_has_only_bounded_block": memory_bounded, "cleanup_complete": summary["cleanup_complete"] and not list(root.glob("artifact-*.json")), "priorities_healthy": 'todos.html' in server, "hud_healthy": 'proxy_hud' in server}

def run_harmful_fixture(root: Path) -> dict:
    run_id = "synthetic-harmful"
    _start(root, run_id)
    case, arm = CASES[0], CASES[0]["arm_order"][0]
    memory_comparison.start_arm(root, run_id=run_id, case_alias=case["alias"], arm=arm, worker_id="worker-harm", card_id="card-harm", conversation_id="conversation-harm")
    result = _result(case["alias"], arm, harmful=True)
    if result["score_receipt"]["harmful"]:
        memory_comparison.abort_run(root, run_id=run_id, code="harmful_result")
        memory_comparison.record_cleanup(root, run_id=run_id, evidence=CLEAN)
    summary = memory_comparison.build_public_summary(root, run_id)
    return {"status": summary["status"], "arm_count": 1, "cleanup_complete": summary["cleanup_complete"]}
