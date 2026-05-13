"""
cli.py — command-line interface for jobtrack.

Uses argparse from the standard library: one less dependency than
click or typer, same readability for this scope. The structure is a
single argparse parser with subcommands, each dispatching to a small
cmd_* function. That keeps each command testable in isolation and
keeps argument-parsing concerns separate from business logic.

Entry point is main(), which is wired to the `jobtrack` console
script in pyproject.toml.
"""
import argparse
import sys
from jobtrack.database import init_db, add_application
from jobtrack.models import Application
from jobtrack.database import init_db, add_application, list_applications
from jobtrack.models import Application
from rich.console import Console
from rich.table import Table
from jobtrack.database import init_db, add_application, list_applications
from jobtrack.stats import summary
from jobtrack.models import Application
from rich.console import Console
from rich.table import Table
from jobtrack.models import Application, Status
from jobtrack.database import init_db, add_application, list_applications, update_status
from jobtrack.database import init_db, add_application, list_applications, update_status
from jobtrack.matcher import rank_jobs
from jobtrack.models import Application, Status
from jobtrack.stats import summary
from rich.console import Console
from rich.table import Table
from pathlib import Path

def cmd_add(args: argparse.Namespace) -> int:
    """
    Create a new Application and persist it.

    init_db is idempotent — calling it on every CLI command is cheap
    (just a CREATE TABLE IF NOT EXISTS) and means the user never has to
    manually initialize anything. First-time experience: zero ceremony.

    The Application model fills in defaults for status (APPLIED),
    source (linkedin), and the two timestamps, so the user only has
    to provide the bare minimum: company + role.
    """
    init_db()
    app = Application(company=args.company, role=args.role)
    new_id = add_application(app)
    print(f"Added application #{new_id}: {app.company} — {app.role}")
    return 0

def _status_style(status: str) -> str:
    """
    Map an application status to a rich color style.

    Why a dict and not if/elif chain? It's a pure value mapping —
    no branching logic — so a lookup table reads more naturally and
    is trivially extensible (one new line per new status, not a
    new elif). The default "white" fallback handles unknown values
    defensively without crashing the table render.
    """
    styles = {
        "applied": "blue",
        "assessment": "cyan",
        "interview": "yellow",
        "offer": "green",
        "rejected": "red",
        "withdrawn": "dim",
        "ghosted": "magenta",
    }
    return styles.get(status, "white")

def _score_style(score: float) -> str:
    """
    Color the score by strength bucket.

    Thresholds match MatchResult.grade() in models.py — kept in sync
    by convention, not by code. If they ever drift the test suite
    would catch the obvious cases but not subtle off-by-one shifts;
    a future refactor could centralize them in one constant.
    """
    if score >= 7.0:
        return "green"
    if score >= 3.0:
        return "yellow"
    return "red"

def cmd_list(args: argparse.Namespace) -> int:
    """
    Print all applications as a rich table.

    Empty database is a real user state (first-time use), not an
    error — we print a friendly hint instead of an empty table or a
    crash. Exit code stays 0 because "nothing to show" isn't a failure.
    """
    init_db()
    apps = list_applications()

    if not apps:
        print("No applications yet. Add one with: jobtrack add --company X --role Y")
        return 0

    table = Table(title=f"Applications ({len(apps)})")
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Company")
    table.add_column("Role")
    table.add_column("Source", style="dim")
    table.add_column("Status")
    table.add_column("Applied", style="dim")

    for app in apps:
        table.add_row(
            str(app.id),
            app.company,
            app.role,
            app.source,
            f"[{_status_style(app.status.value)}]{app.status.value}[/]",
            app.applied_at.strftime("%Y-%m-%d"),
        )

    console = Console()
    console.print(table)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """
    Print the summary statistics in a readable layout.

    Why call summary() (the facade) instead of the individual stat
    functions? The CLI is presentation — composition is the stats
    module's job. If I called total_count, response_rate, etc. one
    by one here, the CLI would have to know which functions exist
    and in what order to present them. summary() centralizes that
    contract.

    Empty database returns a 0% response rate and empty breakdowns
    — the underlying stat functions are total in the math sense
    (defined on empty input), so the CLI doesn't need a special case.
    """
    init_db()
    apps = list_applications()
    data = summary(apps)
    console = Console()

    # Top-line numbers — what the user wants at a glance.
    console.print(f"\n[bold]Total applications:[/bold] {data['total']}")
    console.print(
        f"[bold]Active:[/bold] {data['active_vs_closed']['active']}  "
        f"[bold]Closed:[/bold] {data['active_vs_closed']['closed']}"
    )
    console.print(f"[bold]Response rate:[/bold] {data['response_rate']}%\n")

    # Status breakdown — one row per status, sorted by count descending
    # so the most common shows first. Sorting is a presentation choice,
    # not a stat function concern.
    if data['status_breakdown']:
        status_table = Table(title="By status", show_header=True)
        status_table.add_column("Status")
        status_table.add_column("Count", justify="right")
        for status, count in sorted(
            data['status_breakdown'].items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            status_table.add_row(
                f"[{_status_style(status)}]{status}[/]",
                str(count),
            )
        console.print(status_table)

    # Source breakdown — same shape as status, different data.
    if data['source_breakdown']:
        source_table = Table(title="By source", show_header=True)
        source_table.add_column("Source")
        source_table.add_column("Count", justify="right")
        for source, count in sorted(
            data['source_breakdown'].items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            source_table.add_row(source, str(count))
        console.print(source_table)

    return 0


def cmd_update(args: argparse.Namespace) -> int:
    """
    Change the status of an existing application.

    Returns exit code 1 (not 0) if no application has that id —
    this is a real user error, distinct from "successfully did nothing".
    Shells that chain commands (`jobtrack update 99 && jobtrack list`)
    rely on this signal: a missing id should stop the chain.

    The Status(args.status) construction is the boundary between the
    CLI's string world and the model's typed enum world. argparse has
    already validated the value is one of the enum's members via
    `choices`, so this construction can't raise here.
    """
    init_db()
    new_status = Status(args.status)
    success = update_status(args.id, new_status)

    if not success:
        print(f"No application found with id {args.id}")
        return 1

    print(f"Updated application #{args.id} → {new_status.value}")
    return 0


def cmd_match(args: argparse.Namespace) -> int:
    """
    Rank applications by how well their job descriptions match a CV.

    File handling: we use pathlib instead of open(), and we read with
    utf-8 explicitly so the result is the same on every OS. Implicit
    encoding (Python defaults to the locale) is a classic source of
    "works on my machine" bugs.

    Output shows the top matches with score, company, role, and the
    keywords most-missing from the user's CV — the actionable part.
    Below ~3.0 we color the score red because that's "weak fit"
    territory; above ~7.0 green for "strong fit"; in between yellow.
    """
    cv_path = Path(args.cv)
    if not cv_path.exists():
        print(f"CV file not found: {cv_path}")
        return 1

    cv_text = cv_path.read_text(encoding="utf-8")
    if not cv_text.strip():
        print(f"CV file is empty: {cv_path}")
        return 1

    init_db()
    apps = list_applications()
    if not apps:
        print("No applications in the database yet.")
        return 0

    ranked = rank_jobs(cv_text, apps)
    if not ranked:
        print("No applications with a job description to match against.")
        return 0

    table = Table(title=f"CV match ranking ({len(ranked)} scored)")
    table.add_column("Rank", justify="right", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("Company")
    table.add_column("Role")
    table.add_column("Missing keywords")

    for rank, (app, result) in enumerate(ranked, start=1):
        score_color = _score_style(result.score)
        missing = ", ".join(result.missing_keywords[:3]) or "—"
        table.add_row(
            str(rank),
            f"[{score_color}]{result.score:.1f}[/]",
            app.company,
            app.role,
            missing,
        )

    console = Console()
    console.print(table)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """
    Build the top-level parser and all subcommand parsers.

    Why a separate function? It makes the parser construct-able from
    tests without going through sys.argv, and it keeps main() small.
    """
    parser = argparse.ArgumentParser(
        prog="jobtrack",
        description="Track internship applications from the command line.",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        help="Available commands",
    )

    # add
    p_add = subparsers.add_parser("add", help="Add a new application")
    p_add.add_argument("--company", required=True, help="Company name")
    p_add.add_argument("--role", required=True, help="Role/position title")
    p_add.set_defaults(func=cmd_add)

    # list
    p_list = subparsers.add_parser("list", help="List all applications")
    p_list.set_defaults(func=cmd_list)

    # stats
    p_stats = subparsers.add_parser("stats", help="Show summary statistics")
    p_stats.set_defaults(func=cmd_stats)

    # update
    p_update = subparsers.add_parser("update", help="Update an application's status")
    p_update.add_argument("id", type=int, help="Application ID")
    p_update.add_argument(
        "--status",
        required=True,
        choices=[s.value for s in Status],
        help="New status (one of: applied, assessment, interview, offer, rejected, withdrawn, ghosted)",
    )
    p_update.set_defaults(func=cmd_update)

    # match
    p_match = subparsers.add_parser("match", help="Rank applications against a CV")
    p_match.add_argument("--cv", required=True, help="Path to CV text file")
    p_match.set_defaults(func=cmd_match)

    return parser


def main(argv: list[str] | None = None) -> int:
    """
    Entry point. Returns an exit code (0 success, non-zero error)
    so the shell can chain commands like `jobtrack add ... && jobtrack list`.

    argv parameter is optional for testability — pass a list in tests
    instead of mocking sys.argv.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())