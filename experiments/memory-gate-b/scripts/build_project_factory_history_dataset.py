from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EXPERIMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT / "src"))

from memory_bench.history_dataset import build_history_dataset, write_history_dataset


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic Git-only historical memory dataset."
    )
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--repo-slug", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    dataset = build_history_dataset(args.repo, args.source_sha, args.repo_slug)
    write_history_dataset(dataset, args.output)
    manifest = json.loads(
        (args.output / "manifest.json").read_text(encoding="utf-8")
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
