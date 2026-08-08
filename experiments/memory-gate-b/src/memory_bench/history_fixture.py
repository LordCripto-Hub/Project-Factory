from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from .models import BenchmarkFixture, GoldQuestion, MemoryEvent
from .retrieval import tokenize


class DatasetIdentityError(ValueError):
    """Raised when a history dataset is not the immutable approved fixture."""


@dataclass(frozen=True)
class LoadedHistoryFixture:
    source_sha: str
    repo_slug: str
    dataset_name: str
    fixture: BenchmarkFixture


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DatasetIdentityError(f"cannot read dataset JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise DatasetIdentityError(f"dataset JSON is not an object: {path.name}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in lines if line]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DatasetIdentityError(f"cannot read dataset JSONL: {path.name}") from error
    if not all(isinstance(row, dict) for row in rows):
        raise DatasetIdentityError(f"dataset JSONL contains a non-object: {path.name}")
    return rows


def _query_expansions(alias_document: dict[str, Any]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    aliases = alias_document.get("aliases")
    if not isinstance(aliases, list):
        raise DatasetIdentityError("alias document is malformed")

    token_sets: list[tuple[str, set[str], tuple[str, ...]]] = []
    token_counts: Counter[str] = Counter()
    for row in aliases:
        if not isinstance(row, dict):
            raise DatasetIdentityError("alias row is malformed")
        alias = row.get("alias")
        evidence_keys = row.get("evidence_keys")
        if not isinstance(alias, str) or not isinstance(evidence_keys, list):
            raise DatasetIdentityError("alias row is malformed")
        tokens = set(tokenize(alias))
        token_counts.update(tokens)
        if not tokens or not all(isinstance(value, str) and value for value in evidence_keys):
            raise DatasetIdentityError("alias row is malformed")
        token_sets.append((alias, tokens, tuple(evidence_keys)))

    expansions: list[tuple[str, tuple[str, ...]]] = []
    for alias, tokens, evidence_keys in token_sets:
        unique_tokens = sorted(token for token in tokens if token_counts[token] == 1)
        if len(unique_tokens) != 1:
            raise DatasetIdentityError(
                f"alias must contain exactly one unique token: {alias}"
            )
        expansions.append((unique_tokens[0], evidence_keys))
    return tuple(expansions)


def _convert_rows_to_loaded_fixture(
    dataset: Path,
    manifest: dict[str, Any],
) -> LoadedHistoryFixture:
    event_rows = _read_jsonl(dataset / "events.jsonl")
    question_rows = _read_jsonl(dataset / "questions.jsonl")
    alias_document = _read_json(dataset / "aliases.json")

    events = tuple(
        MemoryEvent(
            event_id=str(row["event_id"]),
            sequence=int(row["sequence"]),
            topic=str(row["topic"]),
            content=str(row["content"]),
            fact_key=row.get("fact_key"),
            fact_value=row.get("fact_value"),
            supersedes=row.get("supersedes"),
            provenance=str(row["provenance"]),
            event_type=str(row.get("event_type", "observation")),
        )
        for row in event_rows
    )
    questions = tuple(
        GoldQuestion(
            question_id=str(row["question_id"]),
            family=str(row["family"]),
            query=str(row["query"]),
            relevant_event_ids=tuple(str(value) for value in row["relevant_event_ids"]),
            expected_values=tuple(str(value) for value in row.get("expected_values", ())),
            expected_absent=bool(row.get("expected_absent", False)),
            target_fact_key=row.get("target_fact_key"),
        )
        for row in question_rows
    )
    expansions = _query_expansions(alias_document)

    if len(events) != manifest.get("event_count"):
        raise DatasetIdentityError("event count does not match manifest")
    if len(questions) != manifest.get("question_count"):
        raise DatasetIdentityError("question count does not match manifest")
    if len(expansions) != manifest.get("alias_count"):
        raise DatasetIdentityError("alias count does not match manifest")

    fixture = BenchmarkFixture(
        seed=0,
        target_tokens=sum(event.approx_tokens for event in events),
        events=events,
        questions=questions,
        query_expansions=expansions,
        benchmark_version=2,
    )
    return LoadedHistoryFixture(
        source_sha=str(manifest["source_sha"]),
        repo_slug=str(manifest["repo_slug"]),
        dataset_name=dataset.name,
        fixture=fixture,
    )


def load_history_fixture(
    dataset_dir: str | Path,
    lock_path: str | Path,
    *,
    verify_checksums: bool = True,
) -> LoadedHistoryFixture:
    dataset = Path(dataset_dir)
    if "preliminary" in dataset.name.casefold():
        raise DatasetIdentityError("preliminary dataset is forbidden")

    lock = _read_json(Path(lock_path))
    if lock.get("schema_version") != 1:
        raise DatasetIdentityError("unsupported dataset lock schema")
    if dataset.name != lock.get("dataset_dir"):
        raise DatasetIdentityError("dataset directory does not match lock")

    files = lock.get("files")
    if not isinstance(files, dict):
        raise DatasetIdentityError("dataset lock file map is malformed")
    if verify_checksums:
        for name, expected in files.items():
            try:
                actual = hashlib.sha256((dataset / name).read_bytes()).hexdigest()
            except OSError as error:
                raise DatasetIdentityError(f"cannot read locked dataset file: {name}") from error
            if actual != expected:
                raise DatasetIdentityError(f"dataset checksum mismatch: {name}")

    manifest = _read_json(dataset / "manifest.json")
    validation = _read_json(dataset / "validation.json")
    if manifest.get("source_sha") != lock.get("source_sha"):
        raise DatasetIdentityError("manifest source SHA mismatch")
    if manifest.get("repo_slug") != lock.get("repo_slug"):
        raise DatasetIdentityError("manifest repository mismatch")
    if validation.get("passed") is not True:
        raise DatasetIdentityError("dataset validation did not pass")
    if validation.get("event_count") != manifest.get("event_count"):
        raise DatasetIdentityError("validation event count does not match manifest")
    if validation.get("question_count") != manifest.get("question_count"):
        raise DatasetIdentityError("validation question count does not match manifest")

    return _convert_rows_to_loaded_fixture(dataset, manifest)
