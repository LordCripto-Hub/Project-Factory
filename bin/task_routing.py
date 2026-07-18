#!/usr/bin/env python3
"""Deterministic, zero-provider-call model routing for MyPeople owner tasks."""
from __future__ import annotations

import copy
import re
import unicodedata


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
PROJECT_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

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
    if not isinstance(tiers, dict) or tuple(tiers.keys()) != TIERS:
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
    if hints.get("taskClass"):
        task_class = hints["taskClass"]
        reasons.append("explicit_task_class")
    elif _contains_signal(text, CRITICAL_SIGNALS):
        task_class = "critical"
        reasons.append("critical_signal")
    elif _contains_signal(text, IMPLEMENTATION_SIGNALS):
        task_class = "implementation"
        reasons.append("implementation_signal")
    elif _contains_signal(text, SIMPLE_SIGNALS):
        task_class = "simple"
        reasons.append("simple_signal")
    else:
        task_class = "simple"
        reasons.append("insufficient_strong_signal")

    inferred_risk = {
        "simple": "low",
        "implementation": "medium",
        "critical": "high",
    }[task_class]
    risk = hints.get("risk") or inferred_risk
    if hints.get("risk"):
        reasons.append("explicit_risk")
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
    target_rank = min(desired_rank, ceiling_rank)
    if target_rank < desired_rank:
        reasons.append("tier_ceiling")
    candidates = [
        tier
        for tier in TIERS
        if _tier_rank(policy, tier) <= target_rank
        and policy["tiers"][tier]["model"] in allowed_models
    ]
    if not candidates:
        raise RoutingError("routing_model_denied")
    selected = max(candidates, key=lambda item: _tier_rank(policy, item))
    if _tier_rank(policy, selected) < target_rank:
        reasons.append("model_allowlist_ceiling")
    return selected


def _next_eligible_tier(policy, tier, ceiling, allowed_models):
    rank = _tier_rank(policy, tier)
    ceiling_rank = _tier_rank(policy, ceiling)
    candidates = [
        candidate
        for candidate in TIERS
        if rank < _tier_rank(policy, candidate) <= ceiling_rank
        and policy["tiers"][candidate]["model"] in allowed_models
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: _tier_rank(policy, item))


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
