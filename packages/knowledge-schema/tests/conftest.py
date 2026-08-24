"""Shared fixtures for the schema suite.

Two deliberate choices here.

First, the ``sys.path`` insert. Every other way of running this suite needs
``pip install -e packages/knowledge-schema`` to have happened first, which makes the
tests unrunnable on a machine that cannot install the package (a locked-down CI
image, or a sandbox with no working index). The arithmetic in ``mastery`` is pure
Python and imports nothing outside the package, so there is no reason to require a
build step to test it. The insert is a no-op when the editable install *is* present.

Second, no database and no I/O. Everything under test here is a pure function or a
model validator, so a fixture is just a keyword dict. ``manifest_kwargs`` exists
because ``SubjectManifest`` has seven required fields and a version pattern that is
easy to get wrong, and a test that fails on an unrelated missing field teaches
nothing.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from learnos_schema.common import MasteryDimension  # noqa: E402  (after the path insert, on purpose)
from learnos_schema.mastery import Evidence  # noqa: E402

#: Fixed instant so recency maths is exact instead of "close enough today".
NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def evidence() -> Any:
    """Build one piece of evidence, defaulting everything the test does not care about.

    ``age_days`` is offered instead of ``created_at`` because every recency test is
    phrased as "how old is this pass", and computing the timestamp at each call site
    is how a suite ends up asserting against the wrong instant.
    """

    def _build(
        score: float = 1.0,
        dimension: MasteryDimension = MasteryDimension.PRACTICE,
        *,
        age_days: float = 0.0,
        weight: float = 1.0,
        hints_used: int = 0,
        skill_id: str = "python.skill.reason-about-closures",
        source_type: str = "practice",
    ) -> Evidence:
        return Evidence(
            skill_id=skill_id,
            dimension=dimension,
            score=score,
            weight=weight,
            source_type=source_type,
            hints_used=hints_used,
            created_at=NOW - timedelta(days=age_days),
        )

    return _build


@pytest.fixture
def manifest_kwargs() -> dict[str, Any]:
    """The minimum a ``SubjectManifest`` needs to validate, shaped like the real one."""
    return {
        "id": "programming.python",
        "domain": {"id": "programming", "title": "Software Engineering", "icon": "code"},
        "subject": "python",
        "title": "Python",
        "description": "A working engineer's route through core Python.",
        "version": "2026.08.0",
        "modes": ["learn", "practice"],
    }


@pytest.fixture
def subjects_root() -> Path:
    """Path to the real subject packages, skipping the test if the tree is not there.

    Loading a real package is the only honest way to test the loader, but this suite
    should not fail because someone moved the content out of the monorepo.
    """
    root = REPO_ROOT / "subjects"
    if not (root / "programming" / "python" / "manifest.json").is_file():
        pytest.skip("no subject packages on disk")
    return root
