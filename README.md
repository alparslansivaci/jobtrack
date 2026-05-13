# jobtrack

A small command-line tool I built while applying for internships.
After 50+ applications scattered across LinkedIn, my Excel sheet
became unreadable, so I wrote this.

It tracks applications in a local SQLite database, gives you stats
(response rate, time-to-reply, distribution by status), and uses
TF-IDF similarity to score how well your CV matches a job listing.

## Status

Day 1 of 7. Data models are in place. Database, stats, matcher
and CLI are coming this week.

## Why TF-IDF instead of an LLM?

Three reasons. First, my CV stays on my machine, no API calls
mean no privacy worries. Second, TF-IDF is deterministic, so the
same input always gives the same score; LLMs aren't. Third, it's
free and runs offline. The trade-off is that TF-IDF doesn't
understand semantic similarity ("ML engineer" vs "AI engineer"),
but for keyword-heavy job listings that turns out to be fine.

## Requirements

- Python 3.10+

## Installation

```bash
git clone <repo-url>
cd jobtrack
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Planned commands

```bash
jobtrack add --company "Microsoft" --role "SWE Intern" --source linkedin
jobtrack update 12 --status interview
jobtrack list --status applied
jobtrack stats
jobtrack match 12 --resume cv.txt
```

## Project structure

```
jobtrack/
├── jobtrack/
│   ├── models.py        # Pydantic models       (day 1, done)
│   ├── database.py      # SQLite layer          (day 2)
│   ├── stats.py         # Aggregation           (day 3)
│   ├── matcher.py       # TF-IDF matching       (day 4)
│   └── cli.py           # CLI commands          (day 5)
└── tests/
```

## Development

```bash
pytest                  # run tests
pytest --cov=jobtrack   # with coverage
```

## License

MIT
