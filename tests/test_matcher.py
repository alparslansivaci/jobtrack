"""
Unit tests for matcher.py.

These tests are deliberately property-based, not value-based. TF-IDF
scores are floats that depend on scikit-learn internals; pinning them
to exact numbers would make the suite brittle across library upgrades.

Instead we test invariants:
  - Identical text scores 10.0
  - Empty inputs return a zero result, no crash
  - Score is always in [0, 10]
  - Keyword extraction lands in the expected list (missing vs strong)
  - rank_jobs sorts descending by score
  - Applications without a job_description are skipped
"""
import pytest

from jobtrack.models import Application, MatchResult, Status
from jobtrack.matcher import match_score, rank_jobs


# ---------------------------------------------------------------------------
# match_score: identity and boundary cases
# ---------------------------------------------------------------------------

def test_match_score_identical_text_returns_ten():
    """
    A document compared to itself has cosine similarity 1.0, which
    we scale to 10.0. This is the strongest invariant we have.
    """
    text = "Python developer with SQL and PostgreSQL experience."
    result = match_score(text, text)
    assert result.score == 10.0


def test_match_score_empty_cv_returns_zero():
    """
    Empty input is not a programmer error; it's a real case (new user
    hasn't pasted a CV yet). Should return a clean zero, not raise.
    """
    result = match_score("", "Looking for Python skills.")
    assert result.score == 0.0
    assert result.missing_keywords == []
    assert result.strong_matches == []


def test_match_score_empty_job_returns_zero():
    """Mirror of the above for the other argument."""
    result = match_score("Python developer.", "")
    assert result.score == 0.0


def test_match_score_completely_unrelated_returns_low_score():
    """
    Two texts with no shared technical vocabulary should score near 0.
    We don't assert == 0 because stop-words filtering might leave one
    accidental shared word; we assert < 2.0 which is a generous bound.
    """
    cv = "Python developer with SQL and PostgreSQL."
    job = "Looking for a graphic designer with Photoshop and Illustrator."
    result = match_score(cv, job)
    assert result.score < 2.0


def test_match_score_result_is_in_valid_range():
    """
    The MatchResult model enforces 0 <= score <= 10 via Pydantic, but
    we still test the function output explicitly. If we ever bypass
    the model construction, this test catches the regression.
    """
    cv = "Python SQL PostgreSQL"
    job = "Python Kubernetes Docker"
    result = match_score(cv, job)
    assert 0.0 <= result.score <= 10.0


# ---------------------------------------------------------------------------
# match_score: keyword extraction
# ---------------------------------------------------------------------------

def test_match_score_missing_keywords_contain_job_only_terms():
    """
    Words that appear in the job but not the CV should land in
    missing_keywords. We use distinctive tokens (kubernetes, docker)
    that are unlikely to be filtered as stop-words.
    """
    cv = "Python developer with SQL."
    job = "Python and Kubernetes and Docker."
    result = match_score(cv, job)
    assert "kubernetes" in result.missing_keywords
    assert "docker" in result.missing_keywords


def test_match_score_strong_matches_contain_shared_terms():
    """
    Words that appear in both texts should land in strong_matches.
    """
    cv = "Python developer with SQL and PostgreSQL."
    job = "Python and SQL and PostgreSQL needed."
    result = match_score(cv, job)
    # We don't require a specific order or completeness — just that
    # the shared terms are surfaced.
    assert "python" in result.strong_matches
    assert "sql" in result.strong_matches


def test_match_score_returns_match_result_instance():
    """
    Type contract: the function returns a MatchResult, not a dict or
    tuple. This protects callers from breaking changes.
    """
    result = match_score("python", "python")
    assert isinstance(result, MatchResult)


# ---------------------------------------------------------------------------
# rank_jobs: ordering and filtering
# ---------------------------------------------------------------------------

def _make_app(company: str, description: str | None) -> Application:
    """
    Local helper so each test reads as a small specification rather
    than a wall of Application(...) constructions. Lives here instead
    of in conftest.py because it's only used by matcher tests.
    """
    return Application(
        company=company,
        role="Engineer",
        job_description=description,
    )


def test_rank_jobs_sorts_descending_by_score():
    """
    The highest-scoring application comes first. This is the ranking
    contract — the whole reason this function exists.
    """
    cv = "Python developer with SQL and PostgreSQL."
    apps = [
        _make_app("BadFit", "React TypeScript design systems."),
        _make_app("GoodFit", "Python SQL PostgreSQL developer."),
        _make_app("OkFit", "Python and Kubernetes."),
    ]
    ranked = rank_jobs(cv, apps)
    # Extract scores in returned order.
    scores = [result.score for _, result in ranked]
    assert scores == sorted(scores, reverse=True)
    # The top result must be GoodFit — strongest invariant.
    top_app, _ = ranked[0]
    assert top_app.company == "GoodFit"


def test_rank_jobs_skips_applications_without_description():
    """
    Applications with job_description=None represent "we haven't filled
    this in yet", not "this is a zero match". They should be absent
    from the ranking, not present with score=0.
    """
    cv = "Python developer."
    apps = [
        _make_app("WithDesc", "Python developer."),
        _make_app("NoDesc", None),
    ]
    ranked = rank_jobs(cv, apps)
    companies = [app.company for app, _ in ranked]
    assert "NoDesc" not in companies
    assert "WithDesc" in companies


def test_rank_jobs_empty_application_list_returns_empty():
    """Edge case: no applications means no ranking."""
    assert rank_jobs("Python developer.", []) == []


def test_rank_jobs_empty_cv_returns_empty():
    """
    Edge case: no CV means we can't compute anything. Same shape as
    match_score's empty-input behavior — consistency between the two
    public functions.
    """
    apps = [_make_app("Anywhere", "Python developer.")]
    assert rank_jobs("", apps) == []


def test_rank_jobs_all_descriptions_none_returns_empty():
    """
    If every application has a missing description, the result is
    empty — same logic as no applications at all.
    """
    cv = "Python developer."
    apps = [_make_app("A", None), _make_app("B", None)]
    assert rank_jobs(cv, apps) == []


def test_rank_jobs_returns_tuples_of_application_and_match_result():
    """
    Type contract: each item is (Application, MatchResult). Callers
    depend on this shape.
    """
    cv = "Python developer."
    apps = [_make_app("Test", "Python and SQL.")]
    ranked = rank_jobs(cv, apps)
    assert len(ranked) == 1
    app, result = ranked[0]
    assert isinstance(app, Application)
    assert isinstance(result, MatchResult)