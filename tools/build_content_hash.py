#!/usr/bin/env python3
"""Compute and stamp a subject package's ``manifest.content_hash``.

This is the "build step" the manifest placeholder refers to. A published
package must carry a real content hash: it pins a learner's in-flight work to
the exact package version they started on, and lets ingestion tell a genuine
content change from a no-op refresh.

Two modes, chosen automatically:

* **authoritative**: if ``learnos_schema`` is importable (i.e. you have run
  ``make install`` / installed the ``knowledge-schema`` package), the hash is
  ``SubjectPackage.compute_content_hash()``: a sha256 over the fully-validated,
  default-filled model dump, excluding the volatile manifest fields
  (``generated_at``, ``published_at``, ``content_hash``). This is the value CI
  and the ingestion pipeline agree on.

* **stdlib-fallback**: if the schema package is not importable (e.g. a minimal
  checkout with no dependencies), the hash is computed with the standard
  library only: a sha256 over every ``*.json`` file in the package, each file
  canonicalised, and the manifest's three volatile fields removed. This has no
  third-party dependencies so it always runs; it is stable and non-placeholder,
  which is enough to publish and to pin a version. Re-run in authoritative mode
  once dependencies are installed to converge on the canonical value.

Usage:
    python3 tools/build_content_hash.py subjects/programming/python
    python3 tools/build_content_hash.py subjects/programming/python --check
    python3 tools/build_content_hash.py subjects/programming/python --stdlib

``--check`` computes the hash and reports whether the manifest is already up to
date without writing (exit code 1 if it would change). ``--stdlib`` forces the
fallback even when the schema is importable, which is useful for a quick,
dependency-free stamp.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

VOLATILE_MANIFEST_FIELDS = ("generated_at", "published_at", "content_hash")


# ---------------------------------------------------------------------------
# authoritative mode: uses the real schema when it is importable
# ---------------------------------------------------------------------------
def _authoritative_hash(package_dir: Path) -> str | None:
    """Return the canonical hash, or None if the schema package is unavailable."""
    try:
        from learnos_schema.package import load_subject_package  # type: ignore
    except Exception:
        return None
    package = load_subject_package(package_dir)
    return package.compute_content_hash()


# ---------------------------------------------------------------------------
# stdlib fallback: no third-party dependencies
# ---------------------------------------------------------------------------
def _canonical_bytes(path: Path, *, is_manifest: bool) -> bytes:
    """Return canonical bytes for one file.

    JSON is re-serialised with sorted keys and tight separators so that
    insignificant formatting (indentation, key order, trailing whitespace)
    never changes the hash. The manifest has its three volatile fields removed
    first, mirroring the exclude set in ``SubjectPackage.compute_content_hash``.
    """
    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Not JSON (should not happen for *.json), hash the raw bytes verbatim.
        return raw.encode("utf-8")
    if is_manifest and isinstance(data, dict):
        for field in VOLATILE_MANIFEST_FIELDS:
            data.pop(field, None)
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _stdlib_hash(package_dir: Path) -> str:
    manifest_path = package_dir / "manifest.json"
    digest = hashlib.sha256()
    files = sorted(p for p in package_dir.rglob("*.json") if not p.name.startswith("_"))
    for path in files:
        rel = path.relative_to(package_dir).as_posix()
        payload = _canonical_bytes(path, is_manifest=(path == manifest_path))
        # Include the relative path so a moved file changes the hash, and a
        # length prefix so file boundaries are unambiguous.
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b"\0")
        digest.update(payload)
    return "sha256:" + digest.hexdigest()


# ---------------------------------------------------------------------------
def compute_hash(package_dir: Path, *, force_stdlib: bool) -> tuple[str, str]:
    """Return ``(hash, mode)`` for the package."""
    if not force_stdlib:
        authoritative = _authoritative_hash(package_dir)
        if authoritative is not None:
            return authoritative, "authoritative"
    return _stdlib_hash(package_dir), "stdlib-fallback"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", type=Path, help="Path to the subject package directory (the one with manifest.json).")
    parser.add_argument("--check", action="store_true", help="Report whether the manifest is up to date; do not write.")
    parser.add_argument("--stdlib", action="store_true", help="Force the dependency-free stdlib fallback.")
    args = parser.parse_args(argv)

    package_dir: Path = args.package
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"error: no manifest.json under {package_dir}", file=sys.stderr)
        return 2

    new_hash, mode = compute_hash(package_dir, force_stdlib=args.stdlib)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current = manifest.get("content_hash")

    if args.check:
        if current == new_hash:
            print(f"up to date ({mode}): {new_hash}")
            return 0
        print(f"stale: manifest has {current!r}, {mode} computes {new_hash}", file=sys.stderr)
        return 1

    manifest["content_hash"] = new_hash
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    note = "" if mode == "authoritative" else "  (run with dependencies installed to get the canonical value)"
    print(f"stamped {manifest_path} [{mode}]{note}")
    print(f"content_hash {new_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
