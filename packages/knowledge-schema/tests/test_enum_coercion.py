"""One config option, four broken invariants.

``SchemaModel`` sets ``use_enum_values=True``, which is a reasonable choice: it means
``model_dump()`` produces JSON-ready strings and nothing downstream has to remember to
call ``.value``. The cost is easy to miss. A field declared as an enum does not hold an
enum after validation, it holds a plain ``str``, so ``field is SomeEnum.MEMBER`` is
always false no matter what the field contains.

Because ``MasteryDimension`` and friends subclass ``str``, ``==`` and dict lookups keep
working, which is exactly why this survives review: the code reads correctly, the type
checker is happy, and only the identity comparisons quietly stop firing. Four of them
had, each disabling a guard that something else depended on. This file exists to keep
them dead.

The one safe case is kept here too, as a counter-example, so nobody "fixes" it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from learnos_schema.common import LifecycleStatus, MasteryDimension
from learnos_schema.execution import ExecutionResult, ExecutionStatus
from learnos_schema.execution import TestResult as CaseResult  # aliased: pytest tries to collect "Test*"
from learnos_schema.manifest import SubjectManifest
from learnos_schema.mastery import Evidence
from learnos_schema.package import load_all_packages

HASH = "sha256:2ae98961183bac1f0efd554c0bd3b6268d1ac8e80728dba4cd417223f327ba22"


class TestEnumFieldsAreCoercedToStrings:
    """The root cause, asserted directly so the other tests here read as consequences."""

    def test_an_enum_field_holds_a_plain_string_after_validation(self) -> None:
        evidence = Evidence(
            skill_id="python.skill.reason-about-closures",
            dimension=MasteryDimension.CONCEPT,
            score=1.0,
            source_type="practice",
        )
        assert evidence.dimension == MasteryDimension.CONCEPT
        assert evidence.dimension == "concept"
        assert not isinstance(evidence.dimension, MasteryDimension)
        assert evidence.dimension is not MasteryDimension.CONCEPT

    def test_equality_and_dict_lookup_survive_the_coercion(self) -> None:
        """Why the bug is invisible in review. Only ``is`` breaks."""
        by_dimension = {MasteryDimension.CONCEPT: "kept"}
        assert by_dimension["concept"] == "kept"
        assert {"concept": "kept"}[MasteryDimension.CONCEPT] == "kept"


class TestExecutionWeightedScore:
    def test_a_successful_run_with_no_tests_scores_one(self) -> None:
        """Plenty of tasks are graded on "it ran and produced the right stdout", with no
        test cases at all. Reading the status by identity made every one of them score
        zero, which is a grading failure rather than a cosmetic one.
        """
        result = ExecutionResult(execution_id="exec-1", status=ExecutionStatus.SUCCEEDED)
        assert result.weighted_score == 1.0

    @pytest.mark.parametrize(
        "status",
        [ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT, ExecutionStatus.OOM, ExecutionStatus.INTERNAL_ERROR],
    )
    def test_an_unsuccessful_run_with_no_tests_scores_zero(self, status: ExecutionStatus) -> None:
        assert ExecutionResult(execution_id="exec-1", status=status).weighted_score == 0.0

    def test_with_tests_the_status_does_not_enter_into_it(self) -> None:
        """Test results are the stronger signal: a run can exit non-zero because one
        case failed, and the score should be the share that passed, not zero.
        """
        result = ExecutionResult(
            execution_id="exec-1",
            status=ExecutionStatus.FAILED,
            tests=[
                CaseResult(test_id="t.1", name="passes", passed=True, weight=3.0),
                CaseResult(test_id="t.2", name="fails", passed=False, weight=1.0),
            ],
        )
        assert result.weighted_score == pytest.approx(0.75)

    def test_zero_total_weight_does_not_divide_by_zero(self) -> None:
        result = ExecutionResult(
            execution_id="exec-1",
            status=ExecutionStatus.SUCCEEDED,
            tests=[CaseResult(test_id="t.1", name="weightless", passed=True, weight=0.0)],
        )
        assert result.weighted_score == 0.0

    def test_is_terminal_is_the_one_identity_check_that_is_safe(self) -> None:
        """It is defined on the enum itself, so ``self`` really is a member. Left as a
        counter-example: the rule is "not on model fields", not "never use ``is``".
        """
        assert ExecutionStatus.SUCCEEDED.is_terminal is True
        assert ExecutionStatus.QUEUED.is_terminal is False
        assert ExecutionStatus.RUNNING.is_terminal is False


class TestPublishedManifestNeedsAHash:
    def test_a_published_manifest_without_a_content_hash_is_rejected(self, manifest_kwargs) -> None:
        """The hash is what makes a published package verifiable. The validator was
        written to enforce that and then never fired once, so the guard existed only in
        the source.
        """
        with pytest.raises(ValidationError, match="content_hash"):
            SubjectManifest(**manifest_kwargs, status=LifecycleStatus.PUBLISHED)

    def test_a_published_manifest_with_a_content_hash_is_accepted(self, manifest_kwargs) -> None:
        manifest = SubjectManifest(**manifest_kwargs, status=LifecycleStatus.PUBLISHED, content_hash=HASH)
        assert manifest.content_hash == HASH

    @pytest.mark.parametrize("status", [LifecycleStatus.DRAFT, LifecycleStatus.IN_REVIEW, LifecycleStatus.APPROVED])
    def test_an_unpublished_manifest_does_not_need_one(self, manifest_kwargs, status: LifecycleStatus) -> None:
        """Requiring the hash before publication would mean recomputing it on every
        edit, which is the reason the check is scoped to published in the first place.
        """
        assert SubjectManifest(**manifest_kwargs, status=status).content_hash is None

    def test_the_string_form_of_the_status_is_treated_the_same(self, manifest_kwargs) -> None:
        """Manifests are loaded from JSON, so in production the value arrives as a
        string and never as an enum member. That path is the one that mattered.
        """
        with pytest.raises(ValidationError, match="content_hash"):
            SubjectManifest(**manifest_kwargs, status="published")


class TestSkipUnpublished:
    def test_published_packages_survive_the_filter(self, subjects_root: Path) -> None:
        """``skip_unpublished=True`` compared the coerced string against the enum by
        identity, so it dropped every package including the published ones and returned
        an empty catalogue with no error.
        """
        everything = load_all_packages(subjects_root)
        published = load_all_packages(subjects_root, skip_unpublished=True)

        assert everything, "the fixture guarantees at least one package on disk"
        expected = {pid for pid, pkg in everything.items() if pkg.manifest.status == LifecycleStatus.PUBLISHED}
        assert expected, "at least one package on disk should be published"
        assert set(published) == expected

    def test_the_filter_is_off_by_default(self, subjects_root: Path) -> None:
        assert set(load_all_packages(subjects_root)) >= set(load_all_packages(subjects_root, skip_unpublished=True))
