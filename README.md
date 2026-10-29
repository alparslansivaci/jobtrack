# jobtrack

[![CI](https://github.com/alparslansivaci/jobtrack/actions/workflows/ci.yml/badge.svg)](https://github.com/alparslansivaci/jobtrack/actions/workflows/ci.yml)

A personal CLI for tracking internship applications, with TF-IDF based CV-to-listing match scoring. Built in Python with SQLite, Pydantic, scikit-learn, and rich.

## Motivation

I was applying for internships through LinkedIn and my Excel sheet had become unreadable around the fiftieth row. I wanted three things a spreadsheet couldn't give me: a single command to add an application, automatic response-rate stats, and a way to rank open postings against my CV without copy-pasting into ChatGPT. jobtrack is the smallest thing that does all three.

## Quick start

```bash
git clone <repo-url>
cd jobtrack
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

jobtrack add --company "Anthropic" --role "ML Intern"
jobtrack list
jobtrack list --status interview
jobtrack stats
jobtrack update 1 --status interview
jobtrack match --cv path/to/cv.txt
```

The database lives at `~/.jobtrack/jobtrack.db` and is created on first use.

## Architecture

Four layers, each with one responsibility:

| Module | Responsibility |
|---|---|
| `models.py` | Pydantic models (`Application`, `MatchResult`, `Status` enum). Data validation at the boundary. |
| `database.py` | SQLite persistence. Free functions over a connection, not a class — the data carrier is already a class. |
| `stats.py` | Pure functions computing counts, ratios, distributions. No I/O. |
| `matcher.py` | TF-IDF vectorization and cosine similarity. Returns structured `MatchResult` objects, not bare floats. |
| `cli.py` | argparse-based command dispatch. Thin orchestration over the four layers. |

## Design decisions

These are the trade-offs I made deliberately. Each could have gone the other way; here is why this one.

**TF-IDF over an LLM embedding.** Determinism (testable with exact assertions), privacy (CV stays local, no API), cost (milliseconds, no key). The trade-off: surface-word matching only — "ML engineer" and "machine learning engineer" don't align. Documented limitation, not a hidden flaw.

**SQLite over Postgres or a JSON file.** SQLite is zero-setup, file-based, transactional, and ships with Python. A JSON file would lose ACID guarantees and force me to write my own query layer. Postgres would be overkill for a single-user local tool.

**CLI over a web UI.** The interesting work is the matcher, stats, and data model. A web frontend would be a lot of code (HTTP layer, state management, CSS) without deepening any of that. For a tool I use daily from the terminal, CLI is the right interface. A web version would be a separate project.

**Pydantic over plain dataclasses.** Models validate at construction with rich error messages, support `extra="forbid"` to catch field-name typos, and serialize to JSON cleanly. Dataclasses would mean writing validation manually in every constructor.

**argparse over click or typer.** Standard library — one less dependency, one less surface to break in CI. More verbose, but the readability is fine for five subcommands and the stability guarantee of stdlib is worth it.

**Free functions in `database.py`, not a Repository class.** The data carrier is already a class (`Application`). Wrapping operations in another class would just be ceremony. Module-level functions with a `db_path` parameter give the same testability without an extra layer.

**`db_path` as a default parameter on every database function.** Production callers ignore it; tests inject `tmp_path` instead. Lightweight dependency injection — the test suite never touches the user's real database, and production code stays clean.

**Idempotent `init_db()` on every CLI command.** `CREATE TABLE IF NOT EXISTS` makes the call a no-op once the database exists. Cost is microseconds, but it means there is no separate setup step the user can forget.

**Layered validation: argparse → Pydantic → SQLite.** Each layer catches a different class of error at its own boundary: syntactic (wrong flags, invalid choices) at argparse, domain (type and range constraints) at Pydantic, integrity (unique, not-null) at SQLite. Errors caught as early as possible.

**Layered exit codes.** `0` for success, `1` for semantic errors (id not found, file missing), `2` for syntactic errors (argparse failures). Shell users chaining commands with `&&` can tell the difference between "you typed it wrong" and "I tried but couldn't."

## Testing

83 tests across the five modules:

| Module | Test count | Focus |
|---|---|---|
| `test_models.py` | 11 | Validation, enum behavior, constraint enforcement |
| `test_database.py` | 24 | Roundtrip persistence, ordering, edge cases |
| `test_stats.py` | 26 | Math correctness + facade contract for `summary()` |
| `test_matcher.py` | 14 | Property-based invariants (identical → 10.0, unrelated → low) |
| `test_cli.py` | 8 | Exit codes, stdout content, database side effects, `--status` filter |

A few principles run through the suite:

- **Property-based assertions where library implementations could drift.** `match_score(text, text) == 10.0` is a mathematical invariant; `match_score(a, b) == 5.7` would be brittle across scikit-learn versions.
- **Contract testing for facades.** `summary()` composes other stat functions; its tests verify the keys, enum-to-string conversion, and JSON-serializability — not the arithmetic, which the underlying functions' tests already cover.
- **Test isolation via temp databases.** CLI tests monkey-patch both `DEFAULT_DB_PATH` and each function's `__defaults__` tuple, because Python evaluates default arguments at function-definition time.

Run the full suite:

```bash
pytest -v
pytest --cov=jobtrack   # with coverage
```

## Roadmap

Five phases, each one usable on its own. The order is by how much a change improves my daily use per hour spent, not by how interesting it is to build. Phase 1 is small CLI gaps I hit every week; phases 4 and 5 are the things I'd most like to build but need the least right now.

### Phase 1 — Round out the CLI

Small changes, mostly exposing what the lower layers already support.

- [x] **`list --status`** — filter by status. Shipped; the database layer had the WHERE clause, the CLI just needed the flag.
- [ ] **`list --limit N`** — pagination. Once the table passes ~40 rows the terminal scroll makes `list` useless without it.
- [ ] **`jobtrack init`** — print the database path and offer `--reset`. The path is documented but not introspectable from the tool itself.
- [ ] **CSV export** (`jobtrack export --csv out.csv`) — the escape hatch for anyone who wants their data back in a spreadsheet. Cheap to add, removes the "what if I want to leave" worry.
- [ ] **N-gram matching** — `ngram_range=(1, 2)` in `matcher.py`, so "REST APIs" becomes one feature instead of two. A precision bump with no new dependencies; the property tests should pass unchanged.
- [ ] **Missing-keyword report** — `match` already computes `missing_keywords` per job; this would aggregate them across all open applications into one list of the terms that appear in postings but not in my CV. That's the actionable output I actually want from the matcher.

### Phase 2 — Less typing, more memory

Reduce the manual data entry that makes any tracker fall behind.

- [ ] **Import from a posting URL** — `jobtrack add --url <posting>` to pull company, role, and description. Site-specific scraping is brittle, so start with a generic readability-style extraction and accept that some sites need manual fixup.
- [ ] **PDF CV input** — `match --cv cv.pdf` via `pypdf`. Most people keep their CV as a PDF; asking for a `.txt` copy is friction.
- [ ] **Interview dates and notes** — `update <id> --interview-at 2026-11-04 --note "panel, 3 people"`. New columns on `applications`, so this needs a lightweight schema migration step in `init_db()`.
- [ ] **"No reply for N days" warning** — `Application.days_in_current_status()` already exists; a `--stale 14` flag on `list` would highlight applications that have sat in `applied` past the threshold. This is the nudge to follow up or mark as ghosted.

### Phase 3 — Web view

- [ ] **FastAPI backend** over the same `database.py` functions. The free-function design pays off here: no ORM session to thread through, just call the functions with a `db_path`.
- [ ] **Minimal web panel** — a single-page table with status filters, read-mostly. Not a replacement for the CLI, which stays the primary interface; this is for glancing at the pipeline from a phone.

### Phase 4 — Semantic matching

The part I'd most enjoy building, deliberately last.

- [ ] **Embedding-based matcher backend** — sentence-transformers behind the same `MatchResult` interface, selected with `match --backend embed`. TF-IDF stays the default: it's deterministic, offline, and fast. Embeddings would be opt-in for people who hit the "ML engineer" vs "machine learning engineer" wall.
- [ ] **CV suggestions** — given the missing-keyword report and a semantic matcher, suggest which sections of the CV to adjust for a specific posting. Suggestions only; the tool never edits the CV.
- [ ] **Multiple CV versions** — store several CVs (`cv add --name backend cv_backend.txt`) and have `match` report which version scores best per posting. Useful for anyone applying across two or three role types.

### Phase 5 — Mobile app

Where I'd like this to end up. Most of my application activity happens away from a terminal: a recruiter emails while I'm on the bus, I hear back from a company between classes. Updating a status should take ten seconds on a phone, not a reminder to do it later.

- [ ] **Phase 3 backend becomes the real API.** The FastAPI layer stops being a read-only view and gains the write endpoints (`add`, `update`, interview notes). The CLI keeps talking to SQLite directly; the app talks to the API. Same `database.py` functions underneath, so there is one source of business logic.
- [ ] **Sync.** This is the first phase that needs state outside one machine. The plan is a single-user server I host myself, with the SQLite file as the source of truth and the phone as a client. No accounts, no multi-tenant anything.
- [ ] **The app itself.** Three screens: pipeline list with status filters, an application detail page with notes and interview dates, and a quick-add. Matching stays server-side; the phone just shows the score. Framework undecided; cross-platform (React Native or Flutter) is the likely answer for one person maintaining it.
- [ ] **Push reminders** — the "no reply for N days" check from phase 2, delivered as a notification instead of a line in `list` output.

The CLI doesn't go away. It stays the fastest way to batch-add applications and run `match`; the app covers the cases where I don't have a laptop open.

### Non-goals

Things I've decided not to build, so the scope stays legible:

- **Auto-applying to postings.** Out of scope and not something I'd want to automate.
- **Multi-user or cloud sync before phase 5.** Until then the SQLite file is the whole state, and anyone who wants sync can put `~/.jobtrack/` in a synced folder. Phase 5 adds sync for exactly one user: me.
- **A web app replacing the CLI.** See the CLI-over-web decision above. Phase 3 is a read-mostly view; phase 5 is a second client, not a replacement.

## Requirements

Python 3.10+. All other dependencies are pinned in `pyproject.toml`.

## License

MIT