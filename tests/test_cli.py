"""
Unit tests for the CLI module.

These tests call main() directly with an argv list instead of spawning
subprocesses. Two reasons: it's faster (no Python startup per test),
and it lets us monkey-patch the database path cleanly so the test
suite never touches the user's real ~/.jobtrack/jobtrack.db.

We test exit codes, stdout content, and database side effects — the
three observable surfaces of a CLI command.
"""
from pathlib import Path

import pytest

from jobtrack.cli import main
from jobtrack import database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """
    Point every database function at a fresh temp file for one test.

    There's a Python subtlety here: every database function declares
    db_path=DEFAULT_DB_PATH as a default argument. Default values are
    evaluated once when the function is defined, so they capture the
    *original* path object — monkeypatching the module constant alone
    is not enough; the captured defaults stay pointing at the real DB.

    Fix: also rebind each function's __defaults__ tuple so that calls
    without an explicit db_path argument see the temp path. This is
    the right place for the workaround — at the test boundary, not in
    the production code, which stays clean.
    """
    db_path = tmp_path / "test_jobtrack.db"

    # Patch the module-level constant (for any code that reads it directly).
    monkeypatch.setattr(database, "DEFAULT_DB_PATH", db_path)

    # Patch each function's captured default. __defaults__ is a tuple
    # of the function's default argument values, in order.
    patched_functions = [
        database.init_db,
        database.add_application,
        database.get_application,
        database.list_applications,
        database.update_status,
        database.delete_application,
    ]
    for func in patched_functions:
        # Each function has db_path as its LAST positional default.
        # Rebuild the tuple with the temp path in the last slot.
        old_defaults = func.__defaults__
        new_defaults = old_defaults[:-1] + (db_path,)
        monkeypatch.setattr(func, "__defaults__", new_defaults)

    return db_path
def test_add_inserts_into_database(temp_db, capsys):
    """
    The add command should insert a row and print a confirmation
    that includes the new id. Three things to verify:

      1. Exit code is 0 (happy path)
      2. stdout contains the new application id
      3. The database actually got the row
    """
    exit_code = main(["add", "--company", "Anthropic", "--role", "ML Intern"])

    # 1. Exit code
    assert exit_code == 0

    # 2. stdout — capsys captures print() output for assertions
    captured = capsys.readouterr()
    assert "Anthropic" in captured.out
    assert "ML Intern" in captured.out
    assert "#1" in captured.out  # first application id

    # 3. Database side effect — read it back through the real API,
    # not via raw SQL, to verify the public interface end-to-end.
    apps = database.list_applications()
    assert len(apps) == 1
    assert apps[0].company == "Anthropic"
    assert apps[0].role == "ML Intern"
def test_list_outputs_application(temp_db, capsys):
    """
    With a record in the database, `list` should print a table that
    contains the application's company and role.

    Note we don't assert the rich table's box-drawing characters or
    exact layout — that would be brittle (rich could change its
    style). We assert the data content, which is the actual contract.
    """
    # Arrange: insert one application by running add.
    main(["add", "--company", "Stripe", "--role", "Backend Engineer"])
    capsys.readouterr()  # discard add's output so list's output is clean

    # Act: run list.
    exit_code = main(["list"])

    # Assert: exit code + content.
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Stripe" in captured.out
    assert "Backend Engineer" in captured.out
def test_list_empty_database_shows_friendly_message(temp_db, capsys):
    """
    Running `list` on a fresh database should print a helpful hint,
    not a traceback or an empty table. Exit code stays 0 because
    "nothing to show" isn't a failure — it's a first-time user state.
    """
    exit_code = main(["list"])

    assert exit_code == 0

    captured = capsys.readouterr()
    # We assert on content, not exact wording — the message could be
    # rephrased without breaking the test, but the user-helpful intent
    # must remain.
    assert "No applications" in captured.out
    assert "jobtrack add" in captured.out  # suggested next step
def test_update_returns_exit_code_1_for_unknown_id(temp_db, capsys):
    """
    Updating a non-existent application id is a semantic error —
    the command is syntactically valid (right flag, valid status
    choice) but can't be fulfilled. The contract is exit code 1,
    distinct from argparse's exit code 2 for syntactic errors.

    This test pins that contract: if someone refactors cmd_update
    to silently no-op or to raise, this test catches it.
    """
    exit_code = main(["update", "99", "--status", "interview"])

    assert exit_code == 1

    captured = capsys.readouterr()
    assert "99" in captured.out  # mentions the id the user passed
    assert "no application" in captured.out.lower()  # the "not found" signal
def test_match_missing_cv_returns_exit_code_1(temp_db, capsys, tmp_path):
    """
    Pointing match at a file that doesn't exist is a semantic error,
    not a syntactic one — argparse accepted the path (any string is
    valid), but the filesystem says no such file. Exit code 1 with a
    helpful message that names the missing path.
    """
    missing_path = tmp_path / "does_not_exist.txt"

    exit_code = main(["match", "--cv", str(missing_path)])

    assert exit_code == 1

    captured = capsys.readouterr()
    assert "not found" in captured.out.lower()
    assert str(missing_path) in captured.out  # the user sees which path failed