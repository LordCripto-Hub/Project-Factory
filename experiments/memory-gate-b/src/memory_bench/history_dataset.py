from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path, PurePosixPath
import re
import subprocess


@dataclass(frozen=True)
class GitCommit:
    sha: str
    timestamp: str
    subject: str
    changed_paths: tuple[str, ...]


@dataclass(frozen=True)
class HistoryEvent:
    event_id: str
    sequence: int
    event_type: str
    topic: str
    content: str
    fact_key: str
    fact_value: str
    supersedes: str | None
    provenance: str
    commit_sha: str
    changed_path: str | None = None


@dataclass(frozen=True)
class HistoryQuestion:
    question_id: str
    family: str
    query: str
    relevant_event_ids: tuple[str, ...]
    expected_values: tuple[str, ...] = ()
    expected_absent: bool = False
    target_fact_key: str | None = None


@dataclass(frozen=True)
class HistoryDataset:
    schema_version: int
    generator_version: str
    repo_slug: str
    source_sha: str
    source_timestamp: str
    events: tuple[HistoryEvent, ...]
    questions: tuple[HistoryQuestion, ...]
    aliases: tuple[tuple[str, tuple[str, ...]], ...]


EXPECTED_FAMILIES = {
    "exact": 20,
    "semantic": 20,
    "temporal": 15,
    "multi_hop": 15,
    "contradiction": 10,
    "continuation": 10,
    "failure": 5,
    "negative": 5,
}

CORRECTIVE_VERBS = (
    "fix",
    "restore",
    "harden",
    "guard",
    "repair",
    "rollback",
    "correct",
)

SECRET_PATTERN = re.compile(
    r"(?:ghp_|github_pat_|sk-|tskey-)[A-Za-z0-9_-]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
HOST_PATH_PATTERN = re.compile(
    r"(?:^|[^A-Za-z0-9])[A-Za-z]:[\\/]|/(?:home|Users|srv|tmp)/"
)


def read_git_history(
    repo_path: str | Path,
    source_sha: str = "HEAD",
) -> tuple[str, tuple[GitCommit, ...]]:
    repo = Path(repo_path)
    try:
        resolved_sha = _git(repo, "rev-parse", "--verify", f"{source_sha}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise ValueError("source SHA must resolve to a commit") from exc
    rows = _git(
        repo,
        "log",
        "--reverse",
        "--no-merges",
        "--format=%H%x1f%ct%x1f%s",
        resolved_sha,
    )
    commits: list[GitCommit] = []
    for row in rows.splitlines():
        sha, timestamp, subject = row.split("\x1f", 2)
        _reject_control_characters(subject, "commit subject")
        raw_paths = _git(
            repo,
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            sha,
        )
        paths = tuple(path for path in raw_paths.splitlines() if path)
        for path in paths:
            _validate_repo_relative_path(path)
        commits.append(GitCommit(sha, timestamp, subject, paths))
    return resolved_sha, tuple(commits)


def build_history_dataset(
    repo_path: str | Path,
    source_sha: str,
    repo_slug: str,
) -> HistoryDataset:
    resolved_sha, commits = read_git_history(repo_path, source_sha)
    if len(commits) < 50:
        raise ValueError("history dataset requires at least 50 non-merge commits")
    corrective_commits = tuple(
        commit
        for commit in commits
        if commit.subject.casefold().split(maxsplit=1)[0].rstrip(":")
        in CORRECTIVE_VERBS
    )
    if len(corrective_commits) < 5:
        raise ValueError("history dataset requires at least five corrective commits")

    events, commit_events, file_events = _build_events(commits, repo_slug)
    repeated_paths = tuple(
        path
        for path in sorted(file_events)
        if len(file_events[path]) >= 2
    )
    if len(repeated_paths) < 15:
        raise ValueError("history dataset requires at least 15 paths changed more than once")

    questions: list[HistoryQuestion] = []
    aliases: list[tuple[str, tuple[str, ...]]] = []

    for index, commit in enumerate(commits[:20], start=1):
        event = commit_events[commit.sha]
        questions.append(
            HistoryQuestion(
                f"hist-exact-{index:03d}",
                "exact",
                f"What committed change is recorded for short SHA {commit.sha[:12]}?",
                (event.event_id,),
                (commit.subject,),
                target_fact_key=event.fact_key,
            )
        )

    for index, commit in enumerate(commits[20:40], start=1):
        event = commit_events[commit.sha]
        primary_path = commit.changed_paths[0] if commit.changed_paths else "repository"
        topic = _path_topic(primary_path)
        alias = f"subsystem-alias-{index:02d}"
        aliases.append((alias, (event.fact_key, topic)))
        questions.append(
            HistoryQuestion(
                f"hist-semantic-{index:03d}",
                "semantic",
                f"Which committed change is linked to {alias}?",
                (event.event_id,),
                (commit.subject,),
                target_fact_key=event.fact_key,
            )
        )

    for index, path in enumerate(repeated_paths[:15], start=1):
        current = file_events[path][-1]
        questions.append(
            HistoryQuestion(
                f"hist-temporal-{index:03d}",
                "temporal",
                f"What is the latest committed change affecting {path}?",
                (current.event_id,),
                (current.fact_value,),
                target_fact_key=current.fact_key,
            )
        )

    for index, commit in enumerate(commits[-15:], start=1):
        commit_event = commit_events[commit.sha]
        if not commit.changed_paths:
            raise ValueError(f"selected multi-hop commit has no changed path: {commit.sha}")
        path = commit.changed_paths[0]
        file_event = next(
            event for event in file_events[path] if event.commit_sha == commit.sha
        )
        questions.append(
            HistoryQuestion(
                f"hist-multi-hop-{index:03d}",
                "multi_hop",
                f"Which change and file are jointly recorded for {commit.sha[:12]}?",
                (commit_event.event_id, file_event.event_id),
                (commit.subject, path),
                target_fact_key=commit_event.fact_key,
            )
        )

    for index, path in enumerate(repeated_paths[:10], start=1):
        current = file_events[path][-1]
        questions.append(
            HistoryQuestion(
                f"hist-contradiction-{index:03d}",
                "contradiction",
                f"Which newer change supersedes the previous record for {path}?",
                (current.event_id,),
                (current.fact_value,),
                target_fact_key=current.fact_key,
            )
        )

    for index, commit in enumerate(commits[:10], start=1):
        next_commit = commits[index]
        next_event = commit_events[next_commit.sha]
        questions.append(
            HistoryQuestion(
                f"hist-continuation-{index:03d}",
                "continuation",
                f"What is the next recorded commit after {commit.sha[:12]}?",
                (next_event.event_id,),
                (next_commit.subject,),
                target_fact_key=next_event.fact_key,
            )
        )

    for index, commit in enumerate(corrective_commits[:5], start=1):
        event = commit_events[commit.sha]
        questions.append(
            HistoryQuestion(
                f"hist-failure-{index:03d}",
                "failure",
                f"Which correction is recorded at {commit.sha[:12]}?",
                (event.event_id,),
                (commit.subject,),
                target_fact_key=event.fact_key,
            )
        )

    for index in range(1, 6):
        target = f"missing:deadbeef{index:04d}"
        questions.append(
            HistoryQuestion(
                f"hist-negative-{index:03d}",
                "negative",
                f"Is there committed evidence for nonexistent key {target}?",
                (),
                expected_absent=True,
                target_fact_key=target,
            )
        )

    source_timestamp = _git(
        Path(repo_path),
        "show",
        "-s",
        "--format=%ct",
        resolved_sha,
    )
    return HistoryDataset(
        schema_version=1,
        generator_version="project-factory-history-v2",
        repo_slug=repo_slug,
        source_sha=resolved_sha,
        source_timestamp=source_timestamp,
        events=events,
        questions=tuple(questions),
        aliases=tuple(aliases),
    )


def validate_history_dataset(dataset: HistoryDataset) -> dict[str, object]:
    family_counts = Counter(question.family for question in dataset.questions)
    if len(dataset.questions) != 100 or family_counts != Counter(EXPECTED_FAMILIES):
        raise ValueError("question family distribution does not match the 100-question contract")
    question_ids = [question.question_id for question in dataset.questions]
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("question IDs must be unique")

    event_by_id = {event.event_id: event for event in dataset.events}
    if len(event_by_id) != len(dataset.events):
        raise ValueError("event IDs must be unique")
    superseded_ids = {
        event.supersedes for event in dataset.events if event.supersedes is not None
    }
    for question in dataset.questions:
        if not set(question.relevant_event_ids).issubset(event_by_id):
            raise ValueError(f"question has missing evidence: {question.question_id}")
        if question.family == "negative":
            if not question.expected_absent or question.relevant_event_ids:
                raise ValueError("negative questions must be evidence-free absence checks")
        if question.family in {"temporal", "contradiction"}:
            current = event_by_id[question.relevant_event_ids[0]]
            if current.supersedes is None or current.event_id in superseded_ids:
                raise ValueError("temporal questions must select the latest superseding event")

    answer_values = {
        value.casefold()
        for question in dataset.questions
        for value in question.expected_values
    }
    for alias, values in dataset.aliases:
        candidates = {alias.casefold(), *(value.casefold() for value in values)}
        if candidates & answer_values:
            raise ValueError("alias contains an expected answer value")
        if any(re.search(r"\b[0-9a-f]{40}\b", candidate) for candidate in candidates):
            raise ValueError("alias contains a full commit SHA")

    for event in dataset.events:
        if not re.fullmatch(r"[0-9a-f]{40}", event.commit_sha):
            raise ValueError(f"invalid commit SHA in event {event.event_id}")
        expected_prefix = f"git+repo://{dataset.repo_slug}@{event.commit_sha}#"
        if not event.provenance.startswith(expected_prefix):
            raise ValueError(f"unbound provenance in event {event.event_id}")
        if event.changed_path is not None:
            _validate_repo_relative_path(event.changed_path)

    serialized = json.dumps(asdict(dataset), ensure_ascii=False, sort_keys=True)
    if HOST_PATH_PATTERN.search(serialized):
        raise ValueError("dataset contains an absolute host path")
    if SECRET_PATTERN.search(serialized):
        raise ValueError("dataset contains a secret-like value")

    return {
        "passed": True,
        "checks": [
            "alias-answer-leakage",
            "canonical-supersession",
            "evidence-references",
            "family-distribution",
            "host-path-scan",
            "provenance-binding",
            "secret-shape-scan",
            "unique-identifiers",
        ],
        "event_count": len(dataset.events),
        "question_count": len(dataset.questions),
        "family_distribution": dict(sorted(family_counts.items())),
    }


def write_history_dataset(
    dataset: HistoryDataset,
    output_dir: str | Path,
) -> dict[str, object]:
    validation = validate_history_dataset(dataset)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    family_counts = Counter(question.family for question in dataset.questions)
    manifest = {
        "schema_version": dataset.schema_version,
        "generator_version": dataset.generator_version,
        "repo_slug": dataset.repo_slug,
        "source_sha": dataset.source_sha,
        "source_timestamp": dataset.source_timestamp,
        "event_count": len(dataset.events),
        "question_count": len(dataset.questions),
        "alias_count": len(dataset.aliases),
        "family_distribution": dict(sorted(family_counts.items())),
        "input_contract": "committed-git-objects-only",
    }
    aliases = {
        "schema_version": dataset.schema_version,
        "aliases": [
            {"alias": alias, "evidence_keys": list(values)}
            for alias, values in dataset.aliases
        ],
    }
    _write_json(output / "manifest.json", manifest)
    _write_jsonl(output / "events.jsonl", (asdict(event) for event in dataset.events))
    _write_jsonl(
        output / "questions.jsonl",
        (asdict(question) for question in dataset.questions),
    )
    _write_json(output / "aliases.json", aliases)
    _write_json(output / "validation.json", validation)
    return validation


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, records: object) -> None:
    lines = [
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for record in records
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _build_events(
    commits: tuple[GitCommit, ...],
    repo_slug: str,
) -> tuple[
    tuple[HistoryEvent, ...],
    dict[str, HistoryEvent],
    dict[str, list[HistoryEvent]],
]:
    events: list[HistoryEvent] = []
    commit_events: dict[str, HistoryEvent] = {}
    file_events: dict[str, list[HistoryEvent]] = {}
    sequence = 0
    for commit in commits:
        sequence += 1
        short_sha = commit.sha[:12]
        commit_event = HistoryEvent(
            event_id=f"commit-{short_sha}",
            sequence=sequence,
            event_type="commit",
            topic="repository-change",
            content=f"{short_sha} {commit.subject}",
            fact_key=f"commit:{short_sha}:subject",
            fact_value=commit.subject,
            supersedes=None,
            provenance=f"git+repo://{repo_slug}@{commit.sha}#commit",
            commit_sha=commit.sha,
        )
        events.append(commit_event)
        commit_events[commit.sha] = commit_event
        for path_index, path in enumerate(commit.changed_paths, start=1):
            sequence += 1
            previous = file_events.get(path, [])
            file_event = HistoryEvent(
                event_id=f"file-{short_sha}-{path_index:03d}",
                sequence=sequence,
                event_type="file_change",
                topic=_path_topic(path),
                content=f"{path} changed by {short_sha}",
                fact_key=f"path:{path}:latest-subject",
                fact_value=commit.subject,
                supersedes=previous[-1].event_id if previous else None,
                provenance=f"git+repo://{repo_slug}@{commit.sha}#path={path}",
                commit_sha=commit.sha,
                changed_path=path,
            )
            events.append(file_event)
            file_events.setdefault(path, []).append(file_event)
    return tuple(events), commit_events, file_events


def _path_topic(path: str) -> str:
    stem = PurePosixPath(path).stem.casefold()
    normalized = "".join(character if character.isalnum() else "-" for character in stem)
    return normalized.strip("-") or "repository"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _reject_control_characters(value: str, label: str) -> None:
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} contains control characters")


def _validate_repo_relative_path(value: str) -> None:
    _reject_control_characters(value, "changed path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"changed path is not repository-relative: {value!r}")
