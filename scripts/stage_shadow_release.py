#!/usr/bin/env python3
"""Stage an immutable shadow release and record its exact uncommitted source digest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def _git_output(project_root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _source_paths(project_root: Path) -> list[Path]:
    output = _git_output(
        project_root, "ls-files", "--cached", "--others", "--exclude-standard"
    )
    paths = [Path(line) for line in output.splitlines() if line]
    dist = project_root / "frontend" / "dist"
    if not dist.joinpath("index.html").is_file():
        raise RuntimeError("frontend production build is missing")
    paths.extend(path.relative_to(project_root) for path in dist.rglob("*") if path.is_file())
    return sorted(set(paths), key=lambda path: path.as_posix())


def _tree_digest(project_root: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for relative in paths:
        path = project_root / relative
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--releases-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = args.project_root.expanduser().resolve()
    releases_dir = args.releases_dir.expanduser().resolve()
    try:
        paths = _source_paths(project_root)
        digest = _tree_digest(project_root, paths)
        base_commit = _git_output(project_root, "rev-parse", "HEAD")
        release_name = f"shadow-{digest[:16]}"
        releases_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
        release = releases_dir / release_name
        if release.exists():
            raise FileExistsError(f"release already exists: {release}")
        temporary = Path(tempfile.mkdtemp(prefix=f".{release_name}.", dir=releases_dir))
        try:
            for relative in paths:
                source = project_root / relative
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            build_info = {
                "format_version": 1,
                "release_kind": "uncommitted_shadow",
                "public_promotion_eligible": False,
                "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "base_commit": base_commit,
                "source_tree_sha256": digest,
                "file_count": len(paths),
            }
            (temporary / "SHADOW_BUILD_INFO.json").write_text(
                json.dumps(build_info, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, release)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        current = releases_dir.parent / "current"
        temporary_link = releases_dir.parent / f".current.{os.getpid()}"
        temporary_link.symlink_to(release)
        os.replace(temporary_link, current)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: shadow release staging failed: {exc}", file=sys.stderr)
        return 1
    print(f"release={release}")
    print(f"base_commit={base_commit}")
    print(f"source_tree_sha256={digest}")
    print("public_promotion_eligible=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
