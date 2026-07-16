#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import shutil
import sys


PRESERVE_AT_ROOT = {"run", "status", "todos"}
PRESERVE_ANYWHERE = {"node_modules"}


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def sync_directory(source: Path, target: Path, *, at_root: bool = False) -> None:
    target.mkdir(parents=True, exist_ok=True)
    preserved = set(PRESERVE_ANYWHERE)
    if at_root:
        preserved.update(PRESERVE_AT_ROOT)
    for existing in target.iterdir():
        if existing.name in preserved:
            continue
        if not (source / existing.name).exists():
            remove_path(existing)
    for incoming in source.iterdir():
        destination = target / incoming.name
        if incoming.is_dir() and not incoming.is_symlink():
            if destination.exists() and not destination.is_dir():
                remove_path(destination)
            sync_directory(incoming, destination)
        else:
            if destination.exists() and destination.is_dir():
                remove_path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(incoming, destination, follow_symlinks=False)


def sync_runtime_source(source: str | Path, target: str | Path) -> None:
    sync_directory(Path(source).resolve(), Path(target).resolve(), at_root=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: sync_runtime_source.py SOURCE TARGET")
    sync_runtime_source(sys.argv[1], sys.argv[2])
