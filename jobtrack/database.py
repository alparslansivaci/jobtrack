"""
SQLite persistence layer.

This module is the only place in the codebase that knows
SQL exists. Everyone else (stats, matcher, cli) talks to
this module through Python functions and never sees a query.

That separation matters for two reasons:
  - If we ever swap SQLite for another database, only this
    file changes; the rest of the app keeps working.
  - Tests can stub this layer out without touching SQL.

The database file lives in the user's home directory by
default so it survives between sessions and isn't tied to
where the user happens to run the command from.
"""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from jobtrack.models import Application, Status


DEFAULT_DB_PATH = Path.home() / ".jobtrack" / "jobtrack.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'linkedin',
    status TEXT NOT NULL DEFAULT 'applied',
    applied_at TEXT NOT NULL,
    last_status_change TEXT NOT NULL,
    job_url TEXT,
    job_description TEXT,
    notes TEXT
)
"""


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """
    Create the database file and the applications table.

    Safe to call repeatedly - CREATE TABLE IF NOT EXISTS
    means the second call is a no-op. We call this on
    every CLI startup so the user never has to manually
    "initialize" anything.

    db_path is a parameter (not hard-coded) so tests can
    point this at a temporary file instead of polluting
    the real database.
    """
    # Make sure the parent folder exists (~/.jobtrack/)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Connect, run schema, commit, close.
    # The `with` block auto-closes the connection even if
    # something raises an exception inside.
    with sqlite3.connect(db_path) as conn:
        conn.execute(SCHEMA)
        conn.commit()

def add_application(app: Application, db_path: Path = DEFAULT_DB_PATH) -> int:
    """
    Insert a new application and return its database id.

    The Application object is expected to have id=None
    (we let SQLite assign it). Datetimes are serialized
    to ISO 8601 strings because SQLite has no native
    datetime type.

    Uses parameterized queries (the ? placeholders) to
    protect against SQL injection - never interpolate
    user input directly into SQL.
    """
    query = """
        INSERT INTO applications (
            company, role, source, status,
            applied_at, last_status_change,
            job_url, job_description, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    # The tuple order MUST match the column order above.
    # Status.value gives us the string ("applied"), not
    # "Status.APPLIED". Datetimes become ISO 8601 strings.
    values = (
        app.company,
        app.role,
        app.source,
        app.status.value,
        app.applied_at.isoformat(),
        app.last_status_change.isoformat(),
        app.job_url,
        app.job_description,
        app.notes,
    )

    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(query, values)
        conn.commit()
        return cursor.lastrowid
def _row_to_application(row: sqlite3.Row) -> Application:
    """
    Convert a SQLite row into an Application object.

    SQLite gives us strings for datetimes; we parse them
    back into datetime objects. Same for status: stored
    as 'applied', restored as Status.APPLIED.

    The leading underscore in the name signals "this is
    an internal helper, don't call it from outside this
    module" - a Python convention, not enforced by the
    language but respected by convention.
    """
    return Application(
        id=row["id"],
        company=row["company"],
        role=row["role"],
        source=row["source"],
        status=Status(row["status"]),
        applied_at=datetime.fromisoformat(row["applied_at"]),
        last_status_change=datetime.fromisoformat(row["last_status_change"]),
        job_url=row["job_url"],
        job_description=row["job_description"],
        notes=row["notes"],
    )

def get_application(
    app_id: int,
    db_path: Path = DEFAULT_DB_PATH,
) -> Application | None:
    """
    Fetch a single application by id.

    Returns None if no application has that id. This is
    a deliberate API choice - we could raise an exception,
    but "not found" isn't really an error, it's an
    expected outcome the caller has to handle anyway.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row  # access columns by name
        cursor = conn.execute(
            "SELECT * FROM applications WHERE id = ?",
            (app_id,),
        )
        row = cursor.fetchone()
        return _row_to_application(row) if row else None


def list_applications(
    status: Status | None = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[Application]:
    """
    Return all applications, optionally filtered by status.

    Ordered by applied_at DESC so the most recent shows up
    first - that's almost always what a user wants when
    they type `jobtrack list`.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        if status is None:
            cursor = conn.execute(
                "SELECT * FROM applications ORDER BY applied_at DESC"
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM applications "
                "WHERE status = ? "
                "ORDER BY applied_at DESC",
                (status.value,),
            )

        return [_row_to_application(row) for row in cursor.fetchall()]
    
from datetime import timezone   # add to top of file if not already there


def update_status(
    app_id: int,
    new_status: Status,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """
    Change the status of an application.

    Also bumps last_status_change to "now" so days_in_current_status()
    starts counting from this moment. That's the whole reason we have
    two separate timestamps in the model.

    Returns True if a row was updated, False if no application with
    that id exists. Same design choice as get_application - "not found"
    isn't really an error, just a fact the caller handles.
    """
    now = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "UPDATE applications "
            "SET status = ?, last_status_change = ? "
            "WHERE id = ?",
            (new_status.value, now, app_id),
        )
        conn.commit()
        # rowcount tells us how many rows the UPDATE actually touched.
        # 0 means "no row had that id" - we report that as False.
        return cursor.rowcount > 0


def delete_application(
    app_id: int,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """
    Remove an application from the database.

    Returns True if a row was deleted, False if no application had
    that id. Useful when the user applies twice by accident or
    wants to clean up old test entries.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM applications WHERE id = ?",
            (app_id,),
        )
        conn.commit()
        return cursor.rowcount > 0

