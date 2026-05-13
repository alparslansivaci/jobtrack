"""
Unit tests for database.py.

Each test gets its own temporary SQLite file via pytest's
tmp_path fixture, so tests are fully isolated - no test
depends on the order or state left behind by another.

We test six functions:
  - init_db: creates the schema, idempotent
  - add_application: inserts and returns the new id
  - get_application: fetches by id, None if not found
  - list_applications: returns all or filtered by status
  - update_status: changes status + bumps timestamp
  - delete_application: removes a row, reports success
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jobtrack.database import (
    init_db,
    add_application,
    get_application,
    list_applications,
    update_status,
    delete_application,
)
from jobtrack.models import Application, Status


# -----------------------------------------------------------
# Helper - builds a fresh Application object for tests
# -----------------------------------------------------------


def _make_app(**overrides) -> Application:
    """
    Build a minimal valid Application, override fields as needed.

    Avoids repeating company='X', role='Y' in every test.
    Tests should focus on the behaviour they're verifying,
    not on boilerplate field-setting.
    """
    defaults = {
        "company": "TestCo",
        "role": "Intern",
    }
    defaults.update(overrides)
    return Application(**defaults)
# -----------------------------------------------------------
# init_db
# -----------------------------------------------------------


def test_init_db_creates_database_file(tmp_path):
    """Calling init_db should create the .db file on disk."""
    db_file = tmp_path / "fresh.db"
    assert not db_file.exists()

    init_db(db_file)

    assert db_file.exists()


def test_init_db_is_idempotent(tmp_path):
    """
    Calling init_db twice must not raise.

    init_db is called on every CLI startup, so it has to be
    safe to invoke when the database already exists. The
    'CREATE TABLE IF NOT EXISTS' clause is what guarantees
    this - we test that promise here.
    """
    db_file = tmp_path / "twice.db"
    init_db(db_file)
    init_db(db_file)  # second call should be silent

    assert db_file.exists()


def test_init_db_creates_parent_directory(tmp_path):
    """
    If the parent folder doesn't exist, init_db should
    create it. Otherwise a fresh install would fail because
    ~/.jobtrack/ doesn't exist on a brand new machine.
    """
    nested = tmp_path / "deeply" / "nested" / "folder" / "db.db"
    assert not nested.parent.exists()

    init_db(nested)

    assert nested.parent.exists()
    assert nested.exists()

# -----------------------------------------------------------
# add_application
# -----------------------------------------------------------


def test_add_application_returns_id(tmp_path):
    """The returned id should be the SQLite-assigned rowid."""
    db_file = tmp_path / "test.db"
    init_db(db_file)

    new_id = add_application(_make_app(), db_path=db_file)

    assert new_id == 1  # first row in a fresh table


def test_add_application_assigns_sequential_ids(tmp_path):
    """
    Each insert should get a higher id than the previous.

    We don't assert exact values beyond the first - SQLite
    guarantees monotonic increase, not contiguous values.
    Locking the test to 1, 2, 3 would couple it to an
    implementation detail we don't actually care about.
    """
    db_file = tmp_path / "test.db"
    init_db(db_file)

    id1 = add_application(_make_app(company="A"), db_path=db_file)
    id2 = add_application(_make_app(company="B"), db_path=db_file)
    id3 = add_application(_make_app(company="C"), db_path=db_file)

    assert id1 < id2 < id3


def test_add_application_persists_required_fields(tmp_path):
    """Round-trip: insert an application and read it back."""
    db_file = tmp_path / "test.db"
    init_db(db_file)

    new_id = add_application(
        _make_app(company="Microsoft", role="SWE Intern"),
        db_path=db_file,
    )

    fetched = get_application(new_id, db_path=db_file)
    assert fetched is not None
    assert fetched.company == "Microsoft"
    assert fetched.role == "SWE Intern"


def test_add_application_persists_optional_fields(tmp_path):
    """
    Optional fields (job_url, job_description, notes) should
    round-trip correctly when set, and come back as None when
    not set.
    """
    db_file = tmp_path / "test.db"
    init_db(db_file)

    # Application with optional fields filled in
    id_full = add_application(
        _make_app(
            company="Stripe",
            job_url="https://stripe.com/jobs/123",
            notes="Referred by Alice",
        ),
        db_path=db_file,
    )

    # Application without them
    id_bare = add_application(_make_app(company="Acme"), db_path=db_file)

    full = get_application(id_full, db_path=db_file)
    bare = get_application(id_bare, db_path=db_file)

    assert full.job_url == "https://stripe.com/jobs/123"
    assert full.notes == "Referred by Alice"
    assert full.job_description is None

    assert bare.job_url is None
    assert bare.notes is None


def test_add_application_uses_defaults(tmp_path):
    """
    When source and status aren't specified, the database
    should store the model's defaults: 'linkedin' and 'applied'.
    """
    db_file = tmp_path / "test.db"
    init_db(db_file)

    new_id = add_application(_make_app(), db_path=db_file)

    fetched = get_application(new_id, db_path=db_file)
    assert fetched.source == "linkedin"
    assert fetched.status == Status.APPLIED


def test_add_application_preserves_datetime_precision(tmp_path):
    """
    Datetimes go through ISO 8601 serialization on the way in
    and parsing on the way out. The round-trip should preserve
    the value to at least the second.
    """
    db_file = tmp_path / "test.db"
    init_db(db_file)

    specific_time = datetime(2026, 4, 15, 10, 30, 0, tzinfo=timezone.utc)
    new_id = add_application(
        _make_app(applied_at=specific_time),
        db_path=db_file,
    )

    fetched = get_application(new_id, db_path=db_file)
    assert fetched.applied_at == specific_time
# -----------------------------------------------------------
# get_application
# -----------------------------------------------------------


def test_get_application_returns_none_for_missing_id(tmp_path):
    """
    A non-existent id should yield None, not an exception.

    This is the documented contract - the CLI relies on
    being able to write 'if app is None: ...' instead of
    wrapping every lookup in try/except.
    """
    db_file = tmp_path / "test.db"
    init_db(db_file)

    result = get_application(999, db_path=db_file)

    assert result is None


def test_get_application_returns_object_when_found(tmp_path):
    """A valid id should return a fully-populated Application."""
    db_file = tmp_path / "test.db"
    init_db(db_file)
    new_id = add_application(
        _make_app(company="Google", role="ML Intern"),
        db_path=db_file,
    )

    result = get_application(new_id, db_path=db_file)

    assert result is not None
    assert result.id == new_id
    assert result.company == "Google"
    assert result.role == "ML Intern"


def test_get_application_restores_status_as_enum(tmp_path):
    """
    Status is stored as a string in SQLite but should come
    back as a Status enum, not a string. This is the row-to-
    object mapper doing its job.
    """
    db_file = tmp_path / "test.db"
    init_db(db_file)
    new_id = add_application(
        _make_app(status=Status.INTERVIEW),
        db_path=db_file,
    )

    result = get_application(new_id, db_path=db_file)

    assert result.status == Status.INTERVIEW
    assert isinstance(result.status, Status)  # not just a string
# -----------------------------------------------------------
# list_applications
# -----------------------------------------------------------


def test_list_applications_returns_empty_for_fresh_db(tmp_path):
    """
    An untouched database should return an empty list, not None.

    Returning None here would force every caller to handle two
    'no results' cases (None and []). An empty list is the
    cleaner contract: callers can always iterate the result.
    """
    db_file = tmp_path / "test.db"
    init_db(db_file)

    result = list_applications(db_path=db_file)

    assert result == []


def test_list_applications_returns_all_when_no_filter(tmp_path):
    """Without a status filter, every application should appear."""
    db_file = tmp_path / "test.db"
    init_db(db_file)
    add_application(_make_app(company="A"), db_path=db_file)
    add_application(_make_app(company="B"), db_path=db_file)
    add_application(_make_app(company="C"), db_path=db_file)

    result = list_applications(db_path=db_file)

    assert len(result) == 3
    companies = {app.company for app in result}
    assert companies == {"A", "B", "C"}


def test_list_applications_orders_newest_first(tmp_path):
    """
    Most recent application by applied_at should come first.

    We don't trust "insertion order" - the query has an
    explicit ORDER BY applied_at DESC, and that's the
    contract we verify here.
    """
    db_file = tmp_path / "test.db"
    init_db(db_file)

    now = datetime.now(timezone.utc)
    add_application(
        _make_app(company="Oldest", applied_at=now - timedelta(days=30)),
        db_path=db_file,
    )
    add_application(
        _make_app(company="Newest", applied_at=now),
        db_path=db_file,
    )
    add_application(
        _make_app(company="Middle", applied_at=now - timedelta(days=10)),
        db_path=db_file,
    )

    result = list_applications(db_path=db_file)

    assert [app.company for app in result] == ["Newest", "Middle", "Oldest"]


def test_list_applications_filters_by_status(tmp_path):
    """When a status is passed, only matching rows return."""
    db_file = tmp_path / "test.db"
    init_db(db_file)
    add_application(_make_app(company="A", status=Status.APPLIED), db_path=db_file)
    add_application(_make_app(company="B", status=Status.INTERVIEW), db_path=db_file)
    add_application(_make_app(company="C", status=Status.INTERVIEW), db_path=db_file)
    add_application(_make_app(company="D", status=Status.REJECTED), db_path=db_file)

    interviews = list_applications(status=Status.INTERVIEW, db_path=db_file)

    assert len(interviews) == 2
    assert {app.company for app in interviews} == {"B", "C"}


def test_list_applications_returns_empty_when_filter_matches_nothing(tmp_path):
    """A status filter with no matches should return [], not None."""
    db_file = tmp_path / "test.db"
    init_db(db_file)
    add_application(_make_app(status=Status.APPLIED), db_path=db_file)

    result = list_applications(status=Status.OFFER, db_path=db_file)

    assert result == []
# -----------------------------------------------------------
# update_status
# -----------------------------------------------------------


def test_update_status_changes_status(tmp_path):
    """A simple status transition: APPLIED -> INTERVIEW."""
    db_file = tmp_path / "test.db"
    init_db(db_file)
    new_id = add_application(_make_app(), db_path=db_file)

    ok = update_status(new_id, Status.INTERVIEW, db_path=db_file)

    assert ok is True
    fetched = get_application(new_id, db_path=db_file)
    assert fetched.status == Status.INTERVIEW


def test_update_status_returns_false_for_missing_id(tmp_path):
    """
    Updating a non-existent row should not raise - it
    should just report 'nothing happened' with False.

    Same design philosophy as delete and get: 'not found'
    is information, not an error.
    """
    db_file = tmp_path / "test.db"
    init_db(db_file)

    ok = update_status(999, Status.INTERVIEW, db_path=db_file)

    assert ok is False


def test_update_status_bumps_last_status_change(tmp_path):
    """
    The whole reason last_status_change exists is so it
    refreshes on every status change. We pin the original
    timestamp to the past, update, and check the new
    timestamp is more recent.
    """
    db_file = tmp_path / "test.db"
    init_db(db_file)

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    new_id = add_application(
        _make_app(last_status_change=week_ago),
        db_path=db_file,
    )

    update_status(new_id, Status.INTERVIEW, db_path=db_file)

    fetched = get_application(new_id, db_path=db_file)
    assert fetched.last_status_change > week_ago


def test_update_status_does_not_change_applied_at(tmp_path):
    """
    applied_at is the original submission time - it must
    NEVER change, even when status changes. The two
    timestamps answer different questions, and this test
    locks that contract.
    """
    db_file = tmp_path / "test.db"
    init_db(db_file)

    original_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    new_id = add_application(
        _make_app(applied_at=original_time),
        db_path=db_file,
    )

    update_status(new_id, Status.INTERVIEW, db_path=db_file)

    fetched = get_application(new_id, db_path=db_file)
    assert fetched.applied_at == original_time


# -----------------------------------------------------------
# delete_application
# -----------------------------------------------------------


def test_delete_application_removes_row(tmp_path):
    """After delete, get_application should return None."""
    db_file = tmp_path / "test.db"
    init_db(db_file)
    new_id = add_application(_make_app(), db_path=db_file)

    ok = delete_application(new_id, db_path=db_file)

    assert ok is True
    assert get_application(new_id, db_path=db_file) is None


def test_delete_application_returns_false_for_missing_id(tmp_path):
    """Deleting a non-existent row reports False, no exception."""
    db_file = tmp_path / "test.db"
    init_db(db_file)

    ok = delete_application(999, db_path=db_file)

    assert ok is False


def test_delete_application_only_removes_target(tmp_path):
    """
    Deleting one row must not affect siblings. This guards
    against the classic SQL mistake of forgetting WHERE
    on a DELETE - which would wipe the entire table.
    """
    db_file = tmp_path / "test.db"
    init_db(db_file)
    id_a = add_application(_make_app(company="A"), db_path=db_file)
    id_b = add_application(_make_app(company="B"), db_path=db_file)
    id_c = add_application(_make_app(company="C"), db_path=db_file)

    delete_application(id_b, db_path=db_file)

    remaining = list_applications(db_path=db_file)
    assert len(remaining) == 2
    assert {app.company for app in remaining} == {"A", "C"}