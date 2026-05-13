"""
Unit tests for models.py.

Test strategy: we only test our own logic. Pydantic's
validation and enum behaviour are library responsibility,
not ours to verify.

Our focus:
  - Application methods (days_since_applied, is_active)
  - MatchResult.grade() uses the right thresholds
  - Default values behave as expected
"""

from datetime import datetime, timedelta, timezone

import pytest

from jobtrack.models import Application, MatchResult, Status


# -----------------------------------------------------------
# Application
# -----------------------------------------------------------


def test_application_minimum_fields():
    """Only company and role should be required to create one."""
    app = Application(company="Microsoft", role="SWE Intern")

    assert app.company == "Microsoft"
    assert app.role == "SWE Intern"
    assert app.status == Status.APPLIED   # default
    assert app.source == "linkedin"        # default
    assert app.id is None                  # DB hasn't assigned it yet


def test_days_since_applied_calculates_correctly():
    """An application made 30 days ago should report age 30."""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    app = Application(
        company="Acme",
        role="Intern",
        applied_at=thirty_days_ago,
    )
    # Small clock-drift tolerance, accept 29 or 30
    assert 29 <= app.days_since_applied() <= 30


def test_is_active_for_open_statuses():
    """APPLIED, ASSESSMENT, INTERVIEW, OFFER should all count as active."""
    open_statuses = [
        Status.APPLIED,
        Status.ASSESSMENT,
        Status.INTERVIEW,
        Status.OFFER,
    ]
    for status in open_statuses:
        app = Application(company="X", role="Y", status=status)
        assert app.is_active(), f"{status} should be active"


def test_is_active_false_for_terminal_statuses():
    """REJECTED, WITHDRAWN, GHOSTED should not count as active."""
    terminal_statuses = [
        Status.REJECTED,
        Status.WITHDRAWN,
        Status.GHOSTED,
    ]
    for status in terminal_statuses:
        app = Application(company="X", role="Y", status=status)
        assert not app.is_active(), f"{status} should be inactive"


def test_application_rejects_unknown_field():
    """extra='forbid' should raise on unknown fields."""
    with pytest.raises(Exception):
        Application(
            company="X",
            role="Y",
            mystery_field="should fail",
        )


# -----------------------------------------------------------
# Status enum
# -----------------------------------------------------------


def test_status_serializes_to_lowercase_string():
    """When writing to SQLite we want 'applied', not 'Status.APPLIED'."""
    assert Status.APPLIED.value == "applied"
    assert Status.GHOSTED.value == "ghosted"


def test_status_can_be_constructed_from_string():
    """When reading from the DB we must round-trip strings back to enums."""
    assert Status("interview") == Status.INTERVIEW
    assert Status("offer") == Status.OFFER


# -----------------------------------------------------------
# MatchResult
# -----------------------------------------------------------


def test_match_result_score_bounds():
    """Score must be within 0-10."""
    with pytest.raises(Exception):
        MatchResult(score=11.0)
    with pytest.raises(Exception):
        MatchResult(score=-0.5)


def test_match_result_grade_thresholds():
    """Verify each threshold in grade()."""
    cases = [
        (8.0, "Strong match"),
        (7.5, "Strong match"),   # boundary
        (6.0, "Decent match"),
        (5.0, "Decent match"),   # boundary
        (3.0, "Weak match"),
        (2.5, "Weak match"),     # boundary
        (1.0, "Poor match"),
        (0.0, "Poor match"),
    ]
    for score, expected in cases:
        result = MatchResult(score=score)
        assert result.grade() == expected, (
            f"expected '{expected}' for score={score}, "
            f"got '{result.grade()}'"
        )


def test_match_result_keyword_lists_default_empty():
    result = MatchResult(score=5.0)
    assert result.missing_keywords == []
    assert result.strong_matches == []


def test_match_result_with_keywords():
    result = MatchResult(
        score=7.2,
        strong_matches=["python", "sql", "git"],
        missing_keywords=["kubernetes", "docker"],
    )
    assert "python" in result.strong_matches
    assert "kubernetes" in result.missing_keywords
    assert result.grade() == "Decent match"
