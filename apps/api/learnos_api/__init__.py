"""LearnOS API: the generic subject runtime.

Nothing in this package knows what Python, AWS or options pricing are. Subjects
arrive as validated ``learnos_schema.SubjectPackage`` data and every route is
written against those shapes, so adding a subject is a content change.
"""

from __future__ import annotations

__version__ = "0.1.0"
