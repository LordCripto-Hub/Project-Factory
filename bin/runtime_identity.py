#!/usr/bin/env python3
"""Read and create the sanitized runtime-image identity manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


UNKNOWN = {"schema": 1, "sha": "unknown", "build": "unknown", "image": "unknown", "state": "unknown"}
SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
BUILD_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}$")
STATES = {"candidate", "live", "unknown"}


def _normalized(value: dict) -> dict | None:
    if not isinstance(value, dict) or value.get("schema") != 1:
        return None
    sha, build, image, state = (value.get(key) for key in ("sha", "build", "image", "state"))
    if (sha, build, image, state) == ("unknown", "unknown", "unknown", "unknown"):
        return dict(UNKNOWN)
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        return None
    if not isinstance(build, str) or not BUILD_RE.fullmatch(build):
        return None
    if not isinstance(image, str) or not IMAGE_RE.fullmatch(image):
        return None
    if state not in STATES:
        return None
    return {"schema": 1, "sha": sha, "build": build, "image": image, "state": state}


def read_runtime_identity(path=None) -> dict:
    target = Path(path or Path(__file__).resolve().parents[1] / "runtime-build.json")
    try:
        if target.is_symlink() or target.stat().st_size > 4096:
            return dict(UNKNOWN)
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return dict(UNKNOWN)
    return _normalized(value) or dict(UNKNOWN)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--state", default="candidate")
    args = parser.parse_args()
    if "unknown" in {args.sha, args.build, args.image}:
        value = dict(UNKNOWN)
    else:
        value = _normalized({"schema": 1, "sha": args.sha, "build": args.build, "image": args.image, "state": args.state})
    if value is None:
        raise SystemExit("invalid_runtime_identity")
    args.write.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
