"""
Unit tests for stats.py.

stats functions are pure - they take a list of Application
objects and return numbers or dicts. No database, no I/O.
That makes these tests fast and trivial to set up: just
construct a list of Application instances by hand.

We focus on:
  - Correct counts for typical mixed inputs
  - Edge cases: empty list, single-status list
  - Boundary cases that exercise the response/non-response split
"""

from jobtrack.models import Application, Status
from jobtrack.stats import (
    total_count,
    active_vs_closed,
    status_breakdown,
    source_breakdown,
    response_rate,
    summary,
)


def _app(status: Status = Status.APPLIED, source: str = "linkedin") -> Application:
    """
    Build a minimal Application with overridable status and source.

    Tests rarely care about company/role - they care about the
    status and source distribution. This helper keeps the test
    bodies focused on what's actually under test.
    """
    return Application(company="TestCo", role="Intern", status=status, source=source)
# -----------------------------------------------------------
# total_count
# -----------------------------------------------------------


def test_total_count_empty_list():
    """Empty input should yield zero, not raise."""
    assert total_count([]) == 0


def test_total_count_matches_list_length():
    """Trivial wrapper around len() - this locks that contract."""
    apps = [_app() for _ in range(7)]
    assert total_count(apps) == 7


# -----------------------------------------------------------
# active_vs_closed
# -----------------------------------------------------------


def test_active_vs_closed_empty_list():
    """Both counts should be zero on empty input."""
    result = active_vs_closed([])
    assert result == {"active": 0, "closed": 0}


def test_active_vs_closed_all_active():
    """When every application is active, closed should be zero."""
    apps = [_app(status=Status.APPLIED), _app(status=Status.INTERVIEW)]
    result = active_vs_closed(apps)
    assert result == {"active": 2, "closed": 0}


def test_active_vs_closed_all_closed():
    """When every application is terminal, active should be zero."""
    apps = [
        _app(status=Status.REJECTED),
        _app(status=Status.WITHDRAWN),
        _app(status=Status.GHOSTED),
    ]
    result = active_vs_closed(apps)
    assert result == {"active": 0, "closed": 3}


def test_active_vs_closed_mixed():
    """The classic mixed case - both buckets non-empty."""
    apps = [
        _app(status=Status.APPLIED),       # active
        _app(status=Status.INTERVIEW),     # active
        _app(status=Status.OFFER),         # active
        _app(status=Status.REJECTED),      # closed
        _app(status=Status.GHOSTED),       # closed
    ]
    result = active_vs_closed(apps)
    assert result == {"active": 3, "closed": 2}


def test_active_vs_closed_sums_to_total():
    """
    Whatever the split, active + closed must equal total.

    This is an *invariant* - a property that should always
    hold regardless of input. Invariant tests are powerful
    because they catch off-by-one errors and miscounting
    bugs across any input shape.
    """
    apps = [
        _app(status=Status.APPLIED),
        _app(status=Status.INTERVIEW),
        _app(status=Status.REJECTED),
        _app(status=Status.WITHDRAWN),
    ]
    result = active_vs_closed(apps)
    assert result["active"] + result["closed"] == len(apps)
# -----------------------------------------------------------
# status_breakdown
# -----------------------------------------------------------


def test_status_breakdown_empty_list():
    """Empty input yields an empty dict, not a pre-filled one with zeros."""
    assert status_breakdown([]) == {}


def test_status_breakdown_counts_each_status():
    """Mixed statuses should produce correct per-status counts."""
    apps = [
        _app(status=Status.APPLIED),
        _app(status=Status.APPLIED),
        _app(status=Status.APPLIED),
        _app(status=Status.INTERVIEW),
        _app(status=Status.REJECTED),
        _app(status=Status.REJECTED),
    ]
    result = status_breakdown(apps)
    assert result[Status.APPLIED] == 3
    assert result[Status.INTERVIEW] == 1
    assert result[Status.REJECTED] == 2


def test_status_breakdown_omits_absent_statuses():
    """
    A status that doesn't appear in the input should be
    absent from the result, not present with value 0.

    The docstring promises this - "missing key means zero".
    Test the contract, not just the easy case.
    """
    apps = [_app(status=Status.APPLIED), _app(status=Status.APPLIED)]
    result = status_breakdown(apps)
    assert result == {Status.APPLIED: 2}
    assert Status.OFFER not in result
    assert Status.GHOSTED not in result


def test_status_breakdown_keys_are_enum_not_string():
    """
    The dict keys should be Status enum instances, not raw
    strings. Lower layers stay type-safe; string conversion
    happens at the summary/CLI boundary, not here.
    """
    apps = [_app(status=Status.INTERVIEW)]
    result = status_breakdown(apps)
    key = next(iter(result.keys()))
    assert isinstance(key, Status)


# -----------------------------------------------------------
# source_breakdown
# -----------------------------------------------------------


def test_source_breakdown_empty_list():
    """Empty input yields an empty dict."""
    assert source_breakdown([]) == {}


def test_source_breakdown_counts_each_source():
    """Mixed sources should produce correct per-source counts."""
    apps = [
        _app(source="linkedin"),
        _app(source="linkedin"),
        _app(source="referral"),
        _app(source="kariyer.net"),
    ]
    result = source_breakdown(apps)
    assert result == {"linkedin": 2, "referral": 1, "kariyer.net": 1}


def test_source_breakdown_treats_casing_as_distinct():
    """
    'LinkedIn' and 'linkedin' must be counted separately.

    This is intentional - normalizing would hide data-entry
    inconsistencies from the user. The breakdown function
    surfaces them so the user sees and fixes them.
    """
    apps = [
        _app(source="linkedin"),
        _app(source="LinkedIn"),
        _app(source="linkedin"),
    ]
    result = source_breakdown(apps)
    assert result["linkedin"] == 2
    assert result["LinkedIn"] == 1
# -----------------------------------------------------------
# response_rate
# -----------------------------------------------------------


def test_response_rate_empty_list():
    """
    Empty input must return 0.0, not raise ZeroDivisionError.

    This is the most important edge case for any function
    that divides - 'no data' is a real scenario, the user
    will see it on day one before they've added anything.
    """
    assert response_rate([]) == 0.0


def test_response_rate_all_applied_returns_zero():
    """Nobody has responded yet - rate should be 0%."""
    apps = [_app(status=Status.APPLIED) for _ in range(5)]
    assert response_rate(apps) == 0.0


def test_response_rate_all_responded_returns_hundred():
    """Every application got some response - rate should be 100%."""
    apps = [
        _app(status=Status.INTERVIEW),
        _app(status=Status.REJECTED),
        _app(status=Status.OFFER),
    ]
    assert response_rate(apps) == 100.0


def test_response_rate_ghosted_does_not_count_as_response():
    """
    GHOSTED is explicitly the 'no response' status, so it
    must lower the rate, not raise it. This is the whole
    reason that status exists.
    """
    apps = [
        _app(status=Status.INTERVIEW),  # response
        _app(status=Status.GHOSTED),    # no response
    ]
    # 1 response out of 2 -> 50%
    assert response_rate(apps) == 50.0


def test_response_rate_withdrawn_counts_as_response():
    """
    WITHDRAWN counts as response because the user typically
    withdraws after some engagement (offer in hand elsewhere,
    role wasn't a fit). Treating it as 'no response' would
    artificially lower the rate due to user's own choices.
    """
    apps = [
        _app(status=Status.APPLIED),     # no response
        _app(status=Status.WITHDRAWN),   # counts as response
    ]
    assert response_rate(apps) == 50.0


def test_response_rate_assessment_counts_as_response():
    """
    Online tests / take-homes are an early response signal.
    The employer engaged, even if they haven't decided yet.
    """
    apps = [
        _app(status=Status.APPLIED),
        _app(status=Status.ASSESSMENT),
    ]
    assert response_rate(apps) == 50.0


def test_response_rate_rounds_to_one_decimal():
    """
    Output should be presentation-ready: one decimal place.
    The actual ratio 1/3 = 33.333... should display as 33.3.
    """
    apps = [
        _app(status=Status.INTERVIEW),
        _app(status=Status.APPLIED),
        _app(status=Status.APPLIED),
    ]
    assert response_rate(apps) == 33.3


def test_response_rate_returns_float_not_int():
    """
    Even at 100%, the result should be a float, so callers
    can format it consistently without surprise.
    """
    apps = [_app(status=Status.INTERVIEW)]
    result = response_rate(apps)
    assert isinstance(result, float)
# ---------------------------------------------------------------------------
# summary() tests
#
# summary is a facade: it composes the other stat functions and returns one
# dict. We do NOT re-test the arithmetic here - those values are covered by
# the individual function tests above. Re-checking them would make these
# tests brittle: a change to total_count would break both test_total_count
# and test_summary, even though only one thing actually changed.
#
# Instead we test summary's OWN responsibilities:
#   - Returns the expected keys (the contract)
#   - Converts enum keys to strings (the docstring promise)
#   - Does not crash on edge cases (empty list)
#   - Result is JSON-serializable (the second docstring promise)
# ---------------------------------------------------------------------------

def test_summary_returns_all_expected_keys():
    """
    summary's contract is that it bundles every stat into one dict.
    If a key goes missing, the CLI's stats command would silently break.
    """
    apps = [_app(status=Status.APPLIED), _app(status=Status.INTERVIEW)]
    result = summary(apps)
    expected_keys = {
        "total",
        "active_vs_closed",
        "status_breakdown",
        "source_breakdown",
        "response_rate",
    }
    assert set(result.keys()) == expected_keys


def test_summary_status_breakdown_uses_string_keys_not_enums():
    """
    The docstring promises string keys at the top level so the result
    is JSON-serializable. status_breakdown() itself returns enum keys;
    summary must convert them.
    """
    apps = [_app(status=Status.APPLIED), _app(status=Status.OFFER)]
    result = summary(apps)
    for key in result["status_breakdown"].keys():
        assert isinstance(key, str)
        # Belt-and-suspenders: make sure it's not an enum that happens
        # to stringify nicely
        assert not isinstance(key, Status)


def test_summary_handles_empty_list_without_crashing():
    """
    A fresh user with zero applications should still get a valid
    summary back, not an exception. The CLI shouldn't have to
    special-case 'no data yet'.
    """
    result = summary([])
    # We don't assert specific values here - the underlying functions'
    # tests already cover what empty means for each. We just assert
    # that the call returns a dict with the right shape.
    assert isinstance(result, dict)
    assert "total" in result


def test_summary_result_is_json_serializable():
    """
    The docstring promises the result can be exposed over an API
    without further conversion. json.dumps is the executable form
    of that promise.
    """
    import json
    apps = [
        _app(status=Status.APPLIED),
        _app(status=Status.INTERVIEW),
        _app(status=Status.OFFER),
    ]
    result = summary(apps)
    # If any value is a non-serializable type (enum, datetime, set),
    # this raises TypeError. No assertion on the output string needed -
    # the fact that it doesn't raise IS the test.
    json.dumps(result)