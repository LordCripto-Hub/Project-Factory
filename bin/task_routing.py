#!/usr/bin/env python3
"""Deterministic, zero-provider-call model routing for MyPeople owner tasks."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import time
import unicodedata

from provider_profiles import validate_profile_id

TIERS = ("economy", "standard", "strong")
TASK_CLASSES = ("simple", "implementation", "critical")
RISKS = ("low", "medium", "high")
TOP_FIELDS = {"schemaVersion", "tiers", "defaults", "projects"}
TIER_FIELDS = {"model", "rank"}
DEFAULT_FIELDS = {
    "tier",
    "maxAutomaticTier",
    "maxAttempts",
    "maxEscalations",
}
PROJECT_FIELDS = {
    "allowedModels",
    "maxAutomaticTier",
    "maxAttempts",
    "maxEscalations",
}
HINT_FIELDS = {"taskClass", "risk", "maxTier"}
DECISION_FIELDS = {
    "schemaVersion",
    "taskId",
    "projectSlug",
    "taskClass",
    "risk",
    "tier",
    "model",
    "providerProfile",
    "selection",
    "reasonCodes",
    "maxAttempts",
    "maxEscalations",
    "attemptCount",
    "escalationCount",
    "nextEligibleTier",
    "aiUsage",
}
PROJECT_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SESSION_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
ESCALATABLE_FAILURES = {
    "verification_failed",
    "implementation_blocked",
    "model_capability_insufficient",
}

SIMPLE_SIGNALS = (
    "document",
    "documentation",
    "explain",
    "format",
    "translate",
    "review",
    "documentar",
    "explicar",
    "formato",
    "traducir",
    "revision",
)
IMPLEMENTATION_SIGNALS = (
    "implement",
    "fix",
    "bug",
    "refactor",
    "api",
    "database",
    "docker",
    "integration",
    "implementar",
    "corregir",
    "refactorizar",
    "base de datos",
    "integracion",
)
CRITICAL_SIGNALS = (
    "security",
    "authentication",
    "secret",
    "production",
    "deploy",
    "payment",
    "data loss",
    "rollback",
    "architecture",
    "seguridad",
    "autenticacion",
    "secreto",
    "produccion",
    "desplegar",
    "pago",
    "perdida de datos",
    "reversion",
    "arquitectura",
)


class RoutingError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _policy_error():
    raise RoutingError("routing_policy_invalid")


def _exact_fields(value, allowed):
    return isinstance(value, dict) and set(value) == set(allowed)


def _positive_int(value, *, allow_zero=False):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= (0 if allow_zero else 1)
    )


def validate_policy(value: dict) -> dict:
    if not _exact_fields(value, TOP_FIELDS):
        _policy_error()
    if value.get("schemaVersion") != 1:
        _policy_error()
    tiers = value.get("tiers")
    if not isinstance(tiers, dict) or set(tiers) != set(TIERS):
        _policy_error()

    ranks = []
    models = []
    for tier in TIERS:
        config = tiers.get(tier)
        if not _exact_fields(config, TIER_FIELDS):
            _policy_error()
        model = config.get("model")
        rank = config.get("rank")
        if (
            not isinstance(model, str)
            or not model.strip()
            or model != model.strip()
            or not _positive_int(rank)
        ):
            _policy_error()
        models.append(model)
        ranks.append(rank)
    if len(set(models)) != len(models):
        _policy_error()
    if len(set(ranks)) != len(ranks) or ranks != sorted(ranks):
        _policy_error()

    defaults = value.get("defaults")
    if not _exact_fields(defaults, DEFAULT_FIELDS):
        _policy_error()
    if (
        defaults.get("tier") not in TIERS
        or defaults.get("maxAutomaticTier") not in TIERS
        or not _positive_int(defaults.get("maxAttempts"))
        or not _positive_int(
            defaults.get("maxEscalations"),
            allow_zero=True,
        )
        or defaults.get("maxEscalations")
        > defaults.get("maxAttempts") - 1
    ):
        _policy_error()
    if (
        tiers[defaults["tier"]]["rank"]
        > tiers[defaults["maxAutomaticTier"]]["rank"]
    ):
        _policy_error()

    projects = value.get("projects")
    if not isinstance(projects, dict) or not projects:
        _policy_error()
    known_models = set(models)
    for slug, project in projects.items():
        if not isinstance(slug, str) or not PROJECT_SLUG.fullmatch(slug):
            _policy_error()
        if not isinstance(project, dict) or not set(project).issubset(
            PROJECT_FIELDS
        ):
            _policy_error()
        allowed = project.get("allowedModels")
        if (
            not isinstance(allowed, list)
            or not allowed
            or any(not isinstance(item, str) for item in allowed)
            or len(set(allowed)) != len(allowed)
            or not set(allowed).issubset(known_models)
        ):
            _policy_error()
        max_tier = project.get(
            "maxAutomaticTier",
            defaults["maxAutomaticTier"],
        )
        max_attempts = project.get(
            "maxAttempts",
            defaults["maxAttempts"],
        )
        max_escalations = project.get(
            "maxEscalations",
            defaults["maxEscalations"],
        )
        if (
            max_tier not in TIERS
            or not _positive_int(max_attempts)
            or not _positive_int(max_escalations, allow_zero=True)
            or max_escalations > max_attempts - 1
        ):
            _policy_error()

    return copy.deepcopy(value)


def _normalize(value) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    plain = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    ).lower()
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def _contains_signal(text: str, signals) -> bool:
    padded = f" {text} "
    return any(f" {signal} " in padded for signal in signals)


def _validated_hints(task_spec) -> dict:
    hints = task_spec.get("routingHints") or {}
    if not isinstance(hints, dict) or not set(hints).issubset(HINT_FIELDS):
        raise RoutingError("routing_task_invalid")
    if hints.get("taskClass") not in (None, *TASK_CLASSES):
        raise RoutingError("routing_task_invalid")
    if hints.get("risk") not in (None, *RISKS):
        raise RoutingError("routing_task_invalid")
    if hints.get("maxTier") not in (None, *TIERS):
        raise RoutingError("routing_task_invalid")
    return dict(hints)


def _task_text(task_spec) -> str:
    commands = task_spec.get("verificationCommands") or []
    if not isinstance(commands, list) or any(
        not isinstance(command, str) for command in commands
    ):
        raise RoutingError("routing_task_invalid")
    for field in ("allowedActions", "forbiddenActions"):
        actions = task_spec.get(field)
        if not isinstance(actions, list) or any(
            not isinstance(action, str) for action in actions
        ):
            raise RoutingError("routing_task_invalid")
    if task_spec.get("evidencePolicy") not in {"optional", "required"}:
        raise RoutingError("routing_task_invalid")
    return _normalize(
        " ".join(
            (
                str(task_spec.get("objective") or ""),
                str(task_spec.get("acceptanceCriteria") or ""),
                " ".join(commands),
            )
        )
    )


def _classify(task_spec):
    hints = _validated_hints(task_spec)
    reasons = []
    text = _task_text(task_spec)
    if _contains_signal(text, CRITICAL_SIGNALS):
        signal_class = "critical"
        reasons.append("critical_signal")
    elif _contains_signal(text, IMPLEMENTATION_SIGNALS):
        signal_class = "implementation"
        reasons.append("implementation_signal")
    elif _contains_signal(text, SIMPLE_SIGNALS):
        signal_class = "simple"
        reasons.append("simple_signal")
    else:
        signal_class = "simple"
        reasons.append("insufficient_strong_signal")

    task_class = signal_class
    if hints.get("taskClass"):
        task_class = max(
            (signal_class, hints["taskClass"]),
            key=TASK_CLASSES.index,
        )
        reasons.append("explicit_task_class")
    inferred_risk = {
        "simple": "low",
        "implementation": "medium",
        "critical": "high",
    }[task_class]
    risk = inferred_risk
    if hints.get("risk"):
        risk = max(
            (inferred_risk, hints["risk"]),
            key=RISKS.index,
        )
        reasons.append("explicit_risk")
    commands = task_spec.get("verificationCommands")
    if (
        task_spec.get("evidencePolicy") == "required"
        and len(commands) > 1
    ):
        risk = RISKS[min(RISKS.index(risk) + 1, len(RISKS) - 1)]
        reasons.append("structural_verification_signal")
    desired_rank = max(
        TASK_CLASSES.index(task_class) + 1,
        RISKS.index(risk) + 1,
    )
    desired_tier = TIERS[desired_rank - 1]
    return task_class, risk, desired_tier, hints, reasons


def _project_policy(policy, slug):
    project = policy["projects"].get(slug)
    if not isinstance(project, dict):
        raise RoutingError("routing_project_missing")
    defaults = policy["defaults"]
    return {
        "allowedModels": list(project["allowedModels"]),
        "maxAutomaticTier": project.get(
            "maxAutomaticTier",
            defaults["maxAutomaticTier"],
        ),
        "maxAttempts": project.get(
            "maxAttempts",
            defaults["maxAttempts"],
        ),
        "maxEscalations": project.get(
            "maxEscalations",
            defaults["maxEscalations"],
        ),
    }


def _tier_rank(policy, tier):
    return policy["tiers"][tier]["rank"]


def _tier_for_model(policy, model):
    for tier in TIERS:
        if policy["tiers"][tier]["model"] == model:
            return tier
    return ""


def _minimum_tier(policy, tiers):
    return min(tiers, key=lambda item: _tier_rank(policy, item))


def _automatic_tier(policy, desired, ceiling, allowed_models, reasons):
    desired_rank = _tier_rank(policy, desired)
    ceiling_rank = _tier_rank(policy, ceiling)
    target = desired if desired_rank <= ceiling_rank else ceiling
    if target != desired:
        reasons.append("tier_ceiling")
    candidates = [
        tier
        for tier in TIERS
        if _tier_rank(policy, target)
        <= _tier_rank(policy, tier)
        <= _tier_rank(policy, ceiling)
        and policy["tiers"][tier]["model"] in allowed_models
    ]
    if not candidates:
        raise RoutingError("routing_model_denied")
    selected = min(candidates, key=lambda item: _tier_rank(policy, item))
    if selected != target:
        reasons.append("model_allowlist_floor")
    return selected


def _next_eligible_tier(policy, tier, ceiling, allowed_models):
    ordered = sorted(TIERS, key=lambda item: _tier_rank(policy, item))
    position = ordered.index(tier) + 1
    if position >= len(ordered):
        return None
    candidate = ordered[position]
    if (
        _tier_rank(policy, candidate) > _tier_rank(policy, ceiling)
        or policy["tiers"][candidate]["model"] not in allowed_models
    ):
        return None
    return candidate


def route_task(
    task_spec,
    policy,
    provider_profile,
    requested_model=None,
) -> dict:
    policy = validate_policy(policy)
    if (
        not isinstance(task_spec, dict)
        or task_spec.get("schemaVersion") != 1
        or not isinstance(task_spec.get("taskId"), str)
        or not task_spec["taskId"].strip()
        or not isinstance(task_spec.get("projectSlug"), str)
        or not isinstance(task_spec.get("objective"), str)
        or not task_spec["objective"].strip()
        or not isinstance(provider_profile, str)
        or not provider_profile.strip()
    ):
        raise RoutingError("routing_task_invalid")

    slug = task_spec["projectSlug"]
    project = _project_policy(policy, slug)
    task_class, risk, desired_tier, hints, reasons = _classify(task_spec)
    default_tier = policy["defaults"]["tier"]
    if (
        "insufficient_strong_signal" in reasons
        and _tier_rank(policy, default_tier)
        > _tier_rank(policy, desired_tier)
    ):
        desired_tier = default_tier
        reasons.append("default_tier")
    project_ceiling = project["maxAutomaticTier"]
    task_ceiling = hints.get("maxTier") or project_ceiling
    ceiling = _minimum_tier(policy, (project_ceiling, task_ceiling))
    if hints.get("maxTier") and _tier_rank(policy, task_ceiling) < _tier_rank(
        policy,
        project_ceiling,
    ):
        reasons.append("task_tier_ceiling")

    allowed_models = project["allowedModels"]
    selection = "automatic"
    if requested_model is not None:
        if not isinstance(requested_model, str) or not requested_model.strip():
            raise RoutingError("routing_model_denied")
        model = requested_model.strip()
        tier = _tier_for_model(policy, model)
        if not tier or model not in allowed_models:
            raise RoutingError("routing_model_denied")
        if _tier_rank(policy, tier) > _tier_rank(policy, ceiling):
            raise RoutingError("routing_tier_denied")
        selection = "manual"
        reasons.append("manual_model")
    else:
        tier = _automatic_tier(
            policy,
            desired_tier,
            ceiling,
            allowed_models,
            reasons,
        )
        model = policy["tiers"][tier]["model"]

    reasons.append("project_policy_allowed")
    next_tier = _next_eligible_tier(
        policy,
        tier,
        ceiling,
        allowed_models,
    )
    return {
        "schemaVersion": 1,
        "taskId": task_spec["taskId"],
        "projectSlug": slug,
        "taskClass": task_class,
        "risk": risk,
        "tier": tier,
        "model": model,
        "providerProfile": provider_profile.strip(),
        "selection": selection,
        "reasonCodes": list(dict.fromkeys(reasons)),
        "maxAttempts": project["maxAttempts"],
        "maxEscalations": project["maxEscalations"],
        "attemptCount": 1,
        "escalationCount": 0,
        "nextEligibleTier": next_tier,
        "aiUsage": "none",
    }


def _contains_forbidden_receipt_key(value) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = re.sub(r"[^a-z0-9]+", "", str(key).lower())
            if (
                any(
                    fragment in lowered
                    for fragment in (
                        "session",
                        "token",
                        "secret",
                        "credential",
                        "password",
                        "apikey",
                    )
                )
            ):
                return True
            if _contains_forbidden_receipt_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_receipt_key(item) for item in value)
    return False


def _contains_sensitive_value(value) -> bool:
    lowered = value.lower()
    return (
        SESSION_UUID.fullmatch(value) is not None
        or "session" in lowered
        or lowered.startswith(("sk-", "tskey-"))
        or any(
            fragment in lowered
            for fragment in (
                "secret",
                "token",
                "credential",
                "password",
                "apikey",
            )
        )
    )


def _safe_provider_profile(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        validate_profile_id(value)
    except ValueError:
        return False
    return True


def _safe_model(value) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and 0 < len(value) <= 128
        and not re.search(r"[\x00-\x1f\x7f]", value)
        and not _contains_sensitive_value(value)
    )


def canonical_decision_bytes(decision) -> bytes:
    reason_codes = (
        decision.get("reasonCodes")
        if isinstance(decision, dict)
        else None
    )
    if (
        not isinstance(decision, dict)
        or set(decision) != DECISION_FIELDS
        or decision.get("schemaVersion") != 1
        or not isinstance(decision.get("taskId"), str)
        or not TASK_ID.fullmatch(decision["taskId"])
        or not isinstance(decision.get("projectSlug"), str)
        or not PROJECT_SLUG.fullmatch(decision["projectSlug"])
        or decision.get("taskClass") not in TASK_CLASSES
        or decision.get("risk") not in RISKS
        or decision.get("tier") not in TIERS
        or not _safe_model(decision.get("model"))
        or not _safe_provider_profile(
            decision.get("providerProfile")
        )
        or decision.get("selection")
        not in {"automatic", "manual", "automatic_escalation"}
        or not isinstance(reason_codes, list)
        or not reason_codes
        or any(
            not isinstance(reason, str)
            or not REASON_CODE.fullmatch(reason)
            for reason in reason_codes
        )
        or not _positive_int(decision.get("maxAttempts"))
        or not _positive_int(
            decision.get("maxEscalations"),
            allow_zero=True,
        )
        or decision.get("maxEscalations")
        > decision.get("maxAttempts") - 1
        or not _positive_int(decision.get("attemptCount"))
        or decision.get("attemptCount") > decision.get("maxAttempts")
        or not _positive_int(
            decision.get("escalationCount"),
            allow_zero=True,
        )
        or decision.get("escalationCount")
        > decision.get("maxEscalations")
        or decision.get("escalationCount")
        > decision.get("attemptCount") - 1
        or decision.get("nextEligibleTier") not in (None, *TIERS)
        or decision.get("aiUsage") != "none"
        or _contains_forbidden_receipt_key(decision)
    ):
        raise RoutingError("routing_task_invalid")
    try:
        rendered = json.dumps(
            decision,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise RoutingError("routing_task_invalid") from error
    return rendered.encode("utf-8") + b"\n"


def write_decision(root, decision) -> tuple[str, str]:
    raw = canonical_decision_bytes(decision)
    task_id = decision["taskId"]
    root_path = Path(root).resolve()
    target = root_path / f"{task_id}.json"
    if target.parent != root_path:
        raise RoutingError("routing_task_invalid")
    root_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root_path, 0o700)
    temporary = root_path / (
        f".{task_id}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    descriptor = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return str(target), hashlib.sha256(raw).hexdigest()


def next_route(decision, failure, policy) -> dict:
    policy = validate_policy(policy)
    if (
        not isinstance(failure, str)
        or failure not in ESCALATABLE_FAILURES
    ):
        raise RoutingError("routing_failure_not_escalatable")
    if not isinstance(decision, dict):
        raise RoutingError("routing_task_invalid")
    canonical_decision_bytes(decision)
    slug = decision.get("projectSlug")
    project = _project_policy(policy, slug)
    current_tier = decision.get("tier")
    current_model = decision.get("model")
    if (
        current_tier not in TIERS
        or policy["tiers"][current_tier]["model"] != current_model
        or current_model not in project["allowedModels"]
    ):
        raise RoutingError("routing_task_invalid")

    attempt_count = decision.get("attemptCount")
    escalation_count = decision.get("escalationCount")
    decision_max_attempts = decision.get("maxAttempts")
    decision_max_escalations = decision.get("maxEscalations")
    if (
        not _positive_int(decision_max_attempts)
        or not _positive_int(
            decision_max_escalations,
            allow_zero=True,
        )
    ):
        raise RoutingError("routing_task_invalid")
    max_attempts = min(
        decision_max_attempts,
        project["maxAttempts"],
    )
    max_escalations = min(
        decision_max_escalations,
        project["maxEscalations"],
    )
    if (
        not _positive_int(attempt_count)
        or not _positive_int(escalation_count, allow_zero=True)
        or attempt_count >= max_attempts
        or escalation_count >= max_escalations
    ):
        raise RoutingError("routing_budget_exhausted")

    expected_next = _next_eligible_tier(
        policy,
        current_tier,
        project["maxAutomaticTier"],
        project["allowedModels"],
    )
    if (
        not expected_next
        or decision.get("nextEligibleTier") != expected_next
    ):
        raise RoutingError("routing_budget_exhausted")

    result = copy.deepcopy(decision)
    result["tier"] = expected_next
    result["model"] = policy["tiers"][expected_next]["model"]
    result["selection"] = "automatic_escalation"
    result["attemptCount"] = attempt_count + 1
    result["escalationCount"] = escalation_count + 1
    result["nextEligibleTier"] = _next_eligible_tier(
        policy,
        expected_next,
        project["maxAutomaticTier"],
        project["allowedModels"],
    )
    reasons = result.get("reasonCodes")
    if not isinstance(reasons, list) or any(
        not isinstance(reason, str) for reason in reasons
    ):
        raise RoutingError("routing_task_invalid")
    result["reasonCodes"] = list(
        dict.fromkeys(
            reasons + [f"escalated_after_{failure}"]
        )
    )
    return result
