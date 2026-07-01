"""Resolve the list of directories to scan for skills.

Skills live in a single canonical location: the ``skills/`` folder at the
trendpower repo root. They are not bundled in the wheel, so the trick is letting
the installed ``trendpower`` binary find that folder.

Resolution order (first existing wins; all are scanned):

1. ``trendpower_SKILLS_DIR`` if set — the explicit escape hatch, used exclusively.
2. ``<cwd>/skills`` and the nearest ancestor of the cwd holding a ``skills/``
   folder — so running from inside the repo just works.
3. The repo-root ``skills/`` discovered by walking up from the installed
   ``trendpower_tui`` / ``trendpower`` package location. With an **editable** install
   (``uv tool install --editable``) the package resolves back to the source
   checkout, so this finds the repo skills with **zero configuration** and
   edits show up live (no env var, no reinstall).
"""

from __future__ import annotations

import os
from pathlib import Path


def discover_skills_dirs(cwd: str | None = None) -> list[str]:
    """Return the ordered list of candidate skill directories."""

    explicit = os.environ.get("trendpower_SKILLS_DIR", "").strip()
    if explicit:
        try:
            resolved = Path(explicit).expanduser().resolve()
        except OSError:
            resolved = Path(explicit)
        return [str(resolved)]

    cwd_path = Path(cwd) if cwd else Path.cwd()
    candidates: list[Path] = [cwd_path / "skills"]

    ancestor = _find_skills_in_ancestors(cwd_path)
    if ancestor is not None:
        candidates.append(ancestor)

    candidates.extend(_package_relative_skills_dirs())

    return _dedupe_existing_first(candidates)


def _find_skills_in_ancestors(start: Path) -> Path | None:
    try:
        cursor = start.resolve()
    except OSError:
        cursor = start
    for parent in [cursor, *cursor.parents]:
        candidate = parent / "skills"
        if _looks_like_skills_dir(candidate):
            return candidate
    return None


def _package_relative_skills_dirs() -> list[Path]:
    """Find ``skills/`` by walking up from the installed package location.

    For an editable install the package ``__file__`` points back into the
    source checkout (``<repo>/trendpower-tui/trendpower_tui/...``), so an ancestor of
    it is the repo root that holds ``skills/``.
    """

    out: list[Path] = []
    for module_name in ("trendpower_tui", "trendpower"):
        try:
            module = __import__(module_name)
        except Exception:
            continue
        spec_file = getattr(module, "__file__", None)
        if not spec_file:
            continue
        pkg_dir = Path(spec_file).resolve().parent
        for parent in pkg_dir.parents:
            candidate = parent / "skills"
            if _looks_like_skills_dir(candidate):
                out.append(candidate)
                break
    return out


def _looks_like_skills_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        for child in path.iterdir():
            if child.is_dir() and (child / "SKILL.md").exists():
                return True
    except OSError:
        return False
    return False


def _dedupe_existing_first(paths: list[Path]) -> list[str]:
    seen: set[str] = set()
    existing: list[str] = []
    pending: list[str] = []
    for path in paths:
        try:
            resolved = str(path.expanduser().resolve())
        except OSError:
            resolved = str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.expanduser().exists():
            existing.append(resolved)
        else:
            pending.append(resolved)
    # Existing paths first so log output reads naturally; non-existent paths
    # still go in so a future-created dir is picked up on restart.
    return [*existing, *pending]
