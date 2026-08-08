#!/usr/bin/env python3
"""Read-only, SHA-locked emergency access to the approved local memory fixture."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


MAX_BYTES = 262_144
MAX_CLAIMS = 3
TOKEN_RE = re.compile(r"[a-z0-9_]+")
REQUIRED_EVENT_FIELDS = {
    "event_id", "sequence", "topic", "content", "provenance", "event_type"
}


def _tokens(value):
    return set(TOKEN_RE.findall(str(value or "").casefold()))


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LocalEmergencyAdapter:
    def __init__(self, dataset_dir, lock_path, runtime_dir):
        self.dataset = Path(dataset_dir).resolve()
        self.lock_path = Path(lock_path).resolve()
        self.runtime = Path(runtime_dir).resolve()

    def _verify_lock(self):
        if "preliminary" in self.dataset.name.casefold():
            raise ValueError("preliminary_dataset_forbidden")
        try:
            lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("dataset_lock_invalid") from error
        if (
            not isinstance(lock, dict)
            or lock.get("schema_version") != 1
            or lock.get("dataset_dir") != self.dataset.name
            or lock.get("repo_slug") != "LordCripto-Hub/Project-Factory"
            or not isinstance(lock.get("files"), dict)
        ):
            raise ValueError("dataset_lock_invalid")
        for name, expected in lock["files"].items():
            if (
                not isinstance(name, str)
                or Path(name).name != name
                or not isinstance(expected, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected)
            ):
                raise ValueError("dataset_lock_invalid")
            path = self.dataset / name
            try:
                actual = _sha256(path)
            except OSError as error:
                raise ValueError("dataset_checksum_mismatch") from error
            if actual != expected:
                raise ValueError("dataset_checksum_mismatch")
        try:
            manifest = json.loads(
                (self.dataset / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("dataset_lock_invalid") from error
        if manifest.get("source_sha") != lock.get("source_sha"):
            raise ValueError("dataset_lock_invalid")

    @staticmethod
    def _claim(row):
        return {
            "id": row["event_id"],
            "projectSlug": "project-factory",
            "content": row["content"],
            "sourceUri": row["provenance"],
            "sourceType": row["event_type"],
            "status": "canonical",
        }

    def _scan(self, query, limit, max_bytes):
        query_tokens = _tokens(query)
        ranked = []
        examined = 0
        with (self.dataset / "events.jsonl").open("rb") as stream:
            while examined < max_bytes:
                remaining = max_bytes - examined
                raw = stream.readline(remaining + 1)
                if not raw:
                    break
                if len(raw) > remaining:
                    examined = max_bytes
                    break
                examined += len(raw)
                try:
                    row = json.loads(raw.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    continue
                if not isinstance(row, dict) or not REQUIRED_EVENT_FIELDS.issubset(row):
                    continue
                if not all(isinstance(row[field], str) and row[field]
                           for field in ("event_id", "topic", "content", "provenance", "event_type")):
                    continue
                searchable = " ".join(str(row.get(field) or "") for field in (
                    "topic", "content", "fact_key", "fact_value", "event_type"
                ))
                overlap = len(query_tokens & _tokens(searchable))
                if overlap:
                    ranked.append((overlap, int(row.get("sequence") or 0), row))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]["event_id"]))
        return [self._claim(item[2]) for item in ranked[:limit]], examined

    def retrieve(self, query, limit=3, max_bytes=MAX_BYTES):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_CLAIMS:
            raise ValueError("invalid_recall_limit")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_BYTES:
            raise ValueError("invalid_byte_limit")
        query = " ".join(str(query or "").split())
        if not query:
            raise ValueError("question_required")
        self._verify_lock()
        self.runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.runtime, 0o700)
        descriptor, name = tempfile.mkstemp(
            prefix="memory-view-", dir=self.runtime, text=True
        )
        path = Path(name)
        try:
            os.chmod(path, 0o600)
            claims, examined = self._scan(query, limit, max_bytes)
            metadata = {
                "selectedEventIds": [claim["id"] for claim in claims],
                "examinedBytes": examined,
            }
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                descriptor = -1
                json.dump(metadata, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            return {
                "claims": claims,
                "examinedCount": len(claims),
                "bytesExamined": examined,
            }
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            path.unlink(missing_ok=True)
