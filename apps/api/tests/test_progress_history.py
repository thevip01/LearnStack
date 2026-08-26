"""The mastery history curve, and the per-dimension breakdown on each point.

The curve is replayed from evidence at read time rather than stored, which is the
property worth testing: a point in the history and today's dashboard are two runs of
the same maths over the same rows, so if they can disagree the whole chart is
decoration. That is what :func:`test_the_last_point_agrees_with_todays_dashboard`
pins, and it is the reason the panel is allowed to plot a dimension at all.
"""

from __future__ import annotations

import httpx
import pytest

from .conftest import ALL_CORRECT, QUIZ, SUBJECT, start_attempt, submit_quiz

pytestmark = pytest.mark.subjects

DIMENSIONS = {"concept", "practice", "lab", "debugging", "production", "retention"}


async def test_history_needs_a_session(api: httpx.AsyncClient) -> None:
    """Reading a subject is open, reading *your* curve is not."""
    response = await api.get(f"/api/v1/progress/{SUBJECT}/history")
    assert response.status_code == 401, response.text


async def test_history_window_is_the_number_of_points(learner: httpx.AsyncClient) -> None:
    for days, expected in ((1, 1), (7, 7), (30, 30)):
        response = await learner.get(f"/api/v1/progress/{SUBJECT}/history", params={"days": days})
        assert response.status_code == 200, response.text
        assert len(response.json()["points"]) == expected


async def test_every_point_carries_all_six_dimensions(learner: httpx.AsyncClient) -> None:
    """Including the days before any evidence existed, where they are unmeasured.

    A missing key and an unmeasured axis are different claims. The chart draws a gap
    for the second one, so the six keys have to be present on every point even when
    the learner had not started yet.
    """
    response = await learner.get(f"/api/v1/progress/{SUBJECT}/history", params={"days": 5})
    points = response.json()["points"]
    assert points, "a window of 5 days should always produce points"
    for point in points:
        assert set(point["dimensions"]) == DIMENSIONS
        for axis in point["dimensions"].values():
            assert set(axis) == {"score", "measured"}


async def test_an_unmeasured_axis_is_not_a_zero(learner: httpx.AsyncClient) -> None:
    """The closures quiz declares `dimension: concept` on every question, so concept
    is the only axis it can move. It says nothing about labs or production.

    `measured: false` with `score: 0.0` is the wire's way of saying "no evidence",
    and the client is required to render a dash. If this ever starts reporting
    `measured: true` for lab off the back of a quiz, a chart somewhere grows a line
    along the floor that looks like failure rather than absence.
    """
    attempt = await start_attempt(learner, QUIZ)
    await submit_quiz(learner, attempt, ALL_CORRECT)

    response = await learner.get(f"/api/v1/progress/{SUBJECT}/history", params={"days": 1})
    today = response.json()["points"][-1]["dimensions"]

    assert today["concept"]["measured"] is True
    assert today["concept"]["score"] > 0
    assert today["lab"]["measured"] is False
    assert today["lab"]["score"] == 0.0
    assert today["production"]["measured"] is False


async def test_the_last_point_agrees_with_todays_dashboard(learner: httpx.AsyncClient) -> None:
    """The end of the curve and the live rollup are the same numbers.

    Both go through ``aggregate_dimensions`` over the same evidence, so this is a
    guard against someone reintroducing a second, drifting implementation for the
    chart's benefit.
    """
    attempt = await start_attempt(learner, QUIZ)
    await submit_quiz(learner, attempt, ALL_CORRECT)

    history = (await learner.get(f"/api/v1/progress/{SUBJECT}/history", params={"days": 2})).json()
    progress = (await learner.get(f"/api/v1/progress/{SUBJECT}")).json()

    last = history["points"][-1]
    assert last["dimensions"] == progress["dimensions"]
    assert last["overall"] == pytest.approx(progress["summary"]["overall"])
    assert last["skills_mastered"] == progress["summary"]["skills_mastered"]


async def test_the_curve_starts_flat_and_ends_where_the_work_is(learner: httpx.AsyncClient) -> None:
    """Yesterday had no evidence, so yesterday's point is honest about it."""
    attempt = await start_attempt(learner, QUIZ)
    await submit_quiz(learner, attempt, ALL_CORRECT)

    points = (await learner.get(f"/api/v1/progress/{SUBJECT}/history", params={"days": 3})).json()["points"]
    assert points[0]["overall"] == 0.0
    assert points[0]["dimensions"]["concept"]["measured"] is False
    assert points[-1]["overall"] > 0.0
    assert points[-1]["dimensions"]["concept"]["measured"] is True
