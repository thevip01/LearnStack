"""The mastery arithmetic.

This module decides what a percentage on a progress page means, so every constant in
it is a product decision rather than an implementation detail: how much a hint costs,
how fast a pass goes stale, whether a dimension with no evidence counts as a zero.
Those are exactly the things a refactor changes without noticing, which is why they
are pinned here by value and not just by shape.

Nothing here touches a database or a network. The whole point of keeping the maths in
the shared package is that the API, the recommender and the ingestion-time difficulty
calibration cannot disagree about it, and that property is only worth anything if it
is tested somewhere both of them can see.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from learnos_schema.common import MasteryDimension
from learnos_schema.mastery import (
    AT_RISK_THRESHOLD,
    DEFAULT_DIMENSION_WEIGHTS,
    EVIDENCE_HALF_LIFE_DAYS,
    HINT_PENALTY_FLOOR,
    HINT_PENALTY_PER_LEVEL,
    MASTERY_THRESHOLD,
    RECENCY_FLOOR,
    Evidence,
    apply_hint_penalty,
    compute_dimension_score,
    compute_skill_mastery,
    target_difficulty,
    update_ability,
)

D = MasteryDimension

#: A real id from the python package. ``Id`` enforces a dotted pattern and a minimum
#: length, so a placeholder like "s" fails validation for reasons unrelated to the test.
SKILL = "python.skill.reason-about-closures"


# ---------------------------------------------------------------------------
# Hints
# ---------------------------------------------------------------------------


class TestHintPenalty:
    def test_no_hints_is_free(self) -> None:
        assert apply_hint_penalty(0.9, 0, D.PRACTICE) == 0.9

    @pytest.mark.parametrize(
        ("hints", "factor"),
        [(1, 0.85), (2, 0.70), (3, 0.55), (4, 0.40)],
    )
    def test_each_hint_costs_a_fixed_fraction(self, hints: int, factor: float) -> None:
        assert apply_hint_penalty(1.0, hints, D.PRACTICE) == pytest.approx(factor)
        assert factor == pytest.approx(max(HINT_PENALTY_FLOOR, 1.0 - HINT_PENALTY_PER_LEVEL * hints))

    def test_the_penalty_bottoms_out_rather_than_reaching_zero(self) -> None:
        """A learner who used ten hints still solved it, and the score has to say so.

        Without a floor, enough hints drive the contribution to zero, which is the same
        number as "never attempted" and destroys the distinction the mastery model is
        built on.
        """
        assert apply_hint_penalty(1.0, 10, D.PRACTICE) == pytest.approx(HINT_PENALTY_FLOOR)
        assert apply_hint_penalty(1.0, 400, D.PRACTICE) == pytest.approx(HINT_PENALTY_FLOOR)

    def test_hints_are_free_on_the_concept_dimension(self) -> None:
        """Reading an explanation while learning a definition is not cheating."""
        assert apply_hint_penalty(1.0, 3, D.CONCEPT) == 1.0

    def test_hints_are_free_on_concept_even_when_the_dimension_arrives_as_a_string(self) -> None:
        """Regression pin. ``SchemaModel`` sets ``use_enum_values=True``, so a dimension
        read back off a model is a plain ``str`` and not a ``MasteryDimension`` member.
        An identity check against the enum silently never matches, which charged the
        hint penalty on concept for every caller that went through ``Evidence``.
        """
        assert apply_hint_penalty(1.0, 3, "concept") == 1.0  # type: ignore[arg-type]

    def test_effective_score_applies_the_penalty_through_the_model(self, evidence) -> None:
        assert evidence(score=1.0, dimension=D.PRACTICE, hints_used=2).effective_score() == pytest.approx(0.70)
        assert evidence(score=1.0, dimension=D.CONCEPT, hints_used=2).effective_score() == pytest.approx(1.0)

    def test_debugging_is_not_exempt(self, evidence) -> None:
        """Being walked through a debugging session is not evidence you can debug."""
        assert evidence(score=1.0, dimension=D.DEBUGGING, hints_used=1).effective_score() == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# Recency
# ---------------------------------------------------------------------------


class TestRecency:
    def test_todays_evidence_is_undiscounted(self, evidence, now) -> None:
        assert evidence(age_days=0).recency_factor(now) == pytest.approx(1.0)

    def test_one_half_life_removes_half_the_discountable_weight(self, evidence, now) -> None:
        expected = RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * 0.5
        assert evidence(age_days=EVIDENCE_HALF_LIFE_DAYS).recency_factor(now) == pytest.approx(expected)
        assert expected == pytest.approx(0.675)

    def test_ancient_evidence_decays_toward_the_floor_but_never_below_it(self, evidence, now) -> None:
        """Ten half-lives is nearly three years. It still counts for something, because
        "wrote a correct closure in 2023" is weak evidence, not absent evidence.
        """
        factor = evidence(age_days=10 * EVIDENCE_HALF_LIFE_DAYS).recency_factor(now)
        assert factor > RECENCY_FLOOR
        assert factor == pytest.approx(RECENCY_FLOOR, abs=1e-3)

    def test_a_clock_skewed_future_timestamp_does_not_inflate_the_weight(self, evidence, now) -> None:
        """Age is clamped at zero, so a submission stamped in the future is worth 1.0
        rather than something above 1.0 that would outweigh every honest attempt.
        """
        assert evidence(age_days=-30).recency_factor(now) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Dimension rollup
# ---------------------------------------------------------------------------


class TestDimensionScore:
    def test_no_evidence_returns_none_rather_than_a_zero(self) -> None:
        """The distinction the whole progress UI rests on. ``None`` becomes a dash;
        a ``DimensionScore`` with ``score=0.0`` renders as 0% and reads as failure.
        """
        assert compute_dimension_score([]) is None

    def test_recency_pulls_the_mean_toward_the_fresher_attempt(self, evidence, now) -> None:
        stale_pass = evidence(score=1.0, age_days=2 * EVIDENCE_HALF_LIFE_DAYS)
        fresh_struggle = evidence(score=0.5, age_days=0)
        computed = compute_dimension_score([stale_pass, fresh_struggle], now)
        assert computed is not None
        assert computed.score == pytest.approx(0.669421, abs=1e-5)
        assert computed.score < 0.75, "a plain mean would say 0.75 and overstate current ability"

    def test_harder_tasks_count_more(self, evidence, now) -> None:
        computed = compute_dimension_score(
            [evidence(score=1.0, weight=3.0), evidence(score=0.0, weight=1.0)], now
        )
        assert computed is not None
        assert computed.score == pytest.approx(0.75), "an unweighted mean would say 0.5"

    def test_it_reports_what_it_measured(self, evidence, now) -> None:
        items = [evidence(age_days=5), evidence(age_days=1), evidence(age_days=30)]
        computed = compute_dimension_score(items, now)
        assert computed is not None
        assert computed.measured is True
        assert computed.evidence_count == 3
        assert computed.last_evidence_at == max(i.created_at for i in items)

    def test_the_score_stays_inside_the_unit_interval(self, evidence, now) -> None:
        computed = compute_dimension_score([evidence(score=1.0) for _ in range(20)], now)
        assert computed is not None
        assert 0.0 <= computed.score <= 1.0


# ---------------------------------------------------------------------------
# Skill rollup
# ---------------------------------------------------------------------------


class TestSkillMastery:
    def test_an_untouched_skill_measures_nothing(self) -> None:
        mastery = compute_skill_mastery("python.skill.reason-about-closures", [])
        assert mastery.state == "untouched"
        assert mastery.evidence_count == 0
        assert mastery.coverage == 0.0
        assert mastery.last_practiced_at is None
        assert all(not d.measured for d in mastery.dimensions.values())
        assert all(d.score == 0.0 for d in mastery.dimensions.values())

    def test_unmeasured_dimensions_leave_the_denominator_instead_of_scoring_zero(self, evidence, now) -> None:
        """The headline rule. A learner who has done the reading and none of the labs
        should see a high score on a small share of the evidence, not a low score that
        looks like failure at something they have not attempted.
        """
        mastery = compute_skill_mastery(
            "python.skill.reason-about-closures", [evidence(score=1.0, dimension=D.CONCEPT)], now=now
        )
        assert mastery.overall == pytest.approx(1.0)
        assert mastery.coverage == pytest.approx(DEFAULT_DIMENSION_WEIGHTS[D.CONCEPT])
        assert mastery.state == "partially_measured"

    def test_every_weighted_dimension_appears_even_with_no_evidence(self, evidence, now) -> None:
        """The API returns a row per dimension so the UI can render a dash for the
        missing ones. Omitting them would make "not measured" indistinguishable from
        "this subject does not use that dimension".
        """
        mastery = compute_skill_mastery(SKILL, [evidence(dimension=D.CONCEPT)], now=now)
        assert set(mastery.dimensions) == {d.value for d in DEFAULT_DIMENSION_WEIGHTS}
        assert mastery.dimensions[D.LAB].measured is False

    def test_overall_is_the_weighted_mean_of_the_measured_dimensions(self, evidence, now) -> None:
        mastery = compute_skill_mastery(
            SKILL,
            [
                evidence(score=1.0, dimension=D.CONCEPT),
                evidence(score=0.9, dimension=D.PRACTICE),
                evidence(score=0.8, dimension=D.LAB),
            ],
            now=now,
        )
        # (1.0*0.20 + 0.9*0.25 + 0.8*0.20) / (0.20 + 0.25 + 0.20)
        assert mastery.overall == pytest.approx(0.9)
        assert mastery.coverage == pytest.approx(0.65)
        assert mastery.evidence_count == 3

    @pytest.mark.parametrize(
        ("score", "state"),
        [(0.9, "mastered"), (0.6, "developing"), (0.4, "at_risk")],
    )
    def test_state_reflects_the_thresholds_once_enough_is_measured(
        self, evidence, now, score: float, state: str
    ) -> None:
        mastery = compute_skill_mastery(
            SKILL,
            [evidence(score=score, dimension=d) for d in (D.CONCEPT, D.PRACTICE, D.LAB)],
            now=now,
        )
        assert mastery.coverage >= 0.5, "the fixture must clear the partially_measured gate"
        assert mastery.state == state
        assert mastery.is_mastered is (state == "mastered")

    def test_thin_coverage_beats_a_high_score_when_naming_the_state(self, evidence, now) -> None:
        """A perfect score on one fifth of the picture is not mastery, and calling it
        mastery is how a learner gets sent to an exam they cannot pass.
        """
        mastery = compute_skill_mastery(SKILL, [evidence(score=1.0, dimension=D.CONCEPT)], now=now)
        assert mastery.overall >= MASTERY_THRESHOLD
        assert mastery.state == "partially_measured"
        assert mastery.is_mastered is False

    def test_a_subject_can_override_the_dimension_mix(self, evidence, now) -> None:
        mastery = compute_skill_mastery(
            SKILL,
            [evidence(score=0.4, dimension=D.CONCEPT), evidence(score=1.0, dimension=D.PRACTICE)],
            weights={D.CONCEPT: 0.9, D.PRACTICE: 0.1},
            now=now,
        )
        assert mastery.overall == pytest.approx(0.4 * 0.9 + 1.0 * 0.1)
        assert set(mastery.dimensions) == {"concept", "practice"}
        assert mastery.coverage == pytest.approx(1.0)

    def test_last_practiced_at_is_the_most_recent_evidence(self, evidence, now) -> None:
        recent = evidence(age_days=1, dimension=D.PRACTICE)
        mastery = compute_skill_mastery(
            SKILL, [evidence(age_days=40, dimension=D.CONCEPT), recent, evidence(age_days=9, dimension=D.LAB)], now=now
        )
        assert mastery.last_practiced_at == recent.created_at

    def test_the_default_weights_sum_to_one(self) -> None:
        """Not required by the maths, which normalises, but a mix that does not sum to
        one means ``coverage`` stops reading as a percentage.
        """
        assert sum(DEFAULT_DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)

    def test_the_thresholds_are_ordered(self) -> None:
        assert 0.0 < AT_RISK_THRESHOLD < MASTERY_THRESHOLD < 1.0


# ---------------------------------------------------------------------------
# Evidence validation
# ---------------------------------------------------------------------------


class TestEvidenceValidation:
    @pytest.mark.parametrize("score", [-0.1, 1.1])
    def test_a_score_outside_the_unit_interval_is_rejected(self, score: float) -> None:
        with pytest.raises(ValidationError):
            Evidence(skill_id="s.k", dimension=D.PRACTICE, score=score, source_type="practice")

    def test_a_zero_weight_is_rejected(self) -> None:
        """Weight zero is evidence that cannot affect anything, which is a caller bug
        rather than a valid observation, and it silently drops out of the mean.
        """
        with pytest.raises(ValidationError):
            Evidence(skill_id="s.k", dimension=D.PRACTICE, score=1.0, source_type="practice", weight=0.0)

    def test_negative_hints_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Evidence(skill_id="s.k", dimension=D.PRACTICE, score=1.0, source_type="practice", hints_used=-1)

    def test_an_unknown_field_is_rejected(self) -> None:
        """``extra="forbid"`` on the shared base model. A typo'd field name would
        otherwise be accepted and silently ignored.
        """
        with pytest.raises(ValidationError):
            Evidence(skill_id="s.k", dimension=D.PRACTICE, score=1.0, source_type="practice", hint_count=2)


# ---------------------------------------------------------------------------
# Adaptive difficulty
# ---------------------------------------------------------------------------


class TestAbility:
    def test_performing_exactly_as_expected_does_not_move_ability(self) -> None:
        """At difficulty equal to ability the model expects a coin flip, so a 0.5 is
        pure confirmation and has to be a no-op. If this drifts, ability wanders on
        its own and every recommendation drifts with it.
        """
        assert update_ability(5.0, 5, 0.5) == pytest.approx(5.0)

    def test_beating_a_hard_task_moves_more_than_beating_an_easy_one(self) -> None:
        from_hard = update_ability(5.0, 8, 1.0)
        from_easy = update_ability(5.0, 2, 1.0)
        assert from_hard > from_easy > 5.0
        assert from_hard == pytest.approx(5.704637, abs=1e-5)
        assert from_easy == pytest.approx(5.095362, abs=1e-5)

    def test_failing_an_easy_task_costs_more_than_failing_a_hard_one(self) -> None:
        assert update_ability(5.0, 2, 0.0) < update_ability(5.0, 8, 0.0) < 5.0

    def test_ability_is_clamped_to_the_difficulty_scale(self) -> None:
        assert update_ability(1.0, 10, 0.0) == pytest.approx(1.0)
        assert update_ability(10.0, 1, 1.0) == pytest.approx(10.0)

    def test_the_expected_curve_is_the_logistic_the_docstring_claims(self) -> None:
        """Pinned so a "simplification" to a linear gap cannot slip through unnoticed."""
        ability, difficulty, score = 4.0, 7.0, 0.75
        expected = 1.0 / (1.0 + math.exp((difficulty - ability) / 1.5))
        assert update_ability(ability, int(difficulty), score) == pytest.approx(ability + 0.8 * (score - expected))


class TestTargetDifficulty:
    def test_it_aims_just_above_current_ability(self) -> None:
        assert target_difficulty(5.2) == 6

    def test_one_failure_steps_down_and_two_step_down_hard(self) -> None:
        assert target_difficulty(5.2, consecutive_failures=1) == 5
        assert target_difficulty(5.2, consecutive_failures=2) == 4

    def test_more_than_two_failures_does_not_keep_digging(self) -> None:
        """Past two, the recommender's job is to send the learner to a prerequisite,
        not to keep lowering difficulty until everything is trivial.
        """
        assert target_difficulty(5.2, consecutive_failures=9) == target_difficulty(5.2, consecutive_failures=2)

    def test_the_result_stays_on_the_one_to_ten_scale(self) -> None:
        assert target_difficulty(1.0, consecutive_failures=5) == 1
        assert target_difficulty(10.0) == 10

    def test_it_never_decreases_as_ability_rises(self) -> None:
        targets = [target_difficulty(a / 10) for a in range(10, 101)]
        assert targets == sorted(targets)

    def test_it_returns_an_int_because_difficulty_is_an_int_field(self) -> None:
        assert isinstance(target_difficulty(5.2), int)
