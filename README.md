# jobtrack

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

80 tests across the five modules:

| Module | Test count | Focus |
|---|---|---|
| `test_models.py` | 11 | Validation, enum behavior, constraint enforcement |
| `test_database.py` | 24 | Roundtrip persistence, ordering, edge cases |
| `test_stats.py` | 26 | Math correctness + facade contract for `summary()` |
| `test_matcher.py` | 14 | Property-based invariants (identical → 10.0, unrelated → low) |
| `test_cli.py` | 5 | Exit codes, stdout content, database side effects |

A few principles run through the suite:

- **Property-based assertions where library implementations could drift.** `match_score(text, text) == 10.0` is a mathematical invariant; `match_score(a, b) == 5.7` would be brittle across scikit-learn versions.
- **Contract testing for facades.** `summary()` composes other stat functions; its tests verify the keys, enum-to-string conversion, and JSON-serializability — not the arithmetic, which the underlying functions' tests already cover.
- **Test isolation via temp databases.** CLI tests monkey-patch both `DEFAULT_DB_PATH` and each function's `__defaults__` tuple, because Python evaluates default arguments at function-definition time.

Run the full suite:

```bash
pytest -v
pytest --cov=jobtrack   # with coverage
```

## What I'd do next

In rough order of impact:

1. **Filter and pagination flags for `list`** — `--status interview`, `--limit 20`. The database layer already supports the first; the CLI just needs to expose it. Five-minute change.
2. **N-gram matching** in `matcher.py`. `ngram_range=(1, 2)` would let "REST APIs" tokenize as a single feature instead of two — a free precision bump.
3. **`jobtrack init` command** to print the database location and reset it. Currently the path is documented but not introspectable.
4. **Sentence-transformer embeddings** as an optional matcher backend. Real semantic similarity, at the cost of determinism and a heavy dependency. Worth it only if a user reports keyword-mismatch problems often.

## Requirements

Python 3.10+. All other dependencies are pinned in `pyproject.toml`.

## License

MIT