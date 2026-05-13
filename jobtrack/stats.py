"""
Aggregation and statistics over application records.

This module is pure-Python: it takes a list of Application
objects and returns numbers and distributions. It never
touches the database directly - the caller (typically the
CLI) is responsible for fetching the list first.

Two reasons for that separation:
  - Functions are easy to test: pass in a hand-crafted list,
    assert on the output. No temporary database needed.
  - The same stats logic would work if the data came from a
    different source (CSV import, an API, etc.) - we're not
    coupled to SQLite.

These are "pure functions" in the functional-programming
sense: same input always produces the same output, no side
effects on the outside world.
"""

from collections import Counter

from jobtrack.models import Application, Status
def total_count(apps: list[Application]) -> int:
    """
    Number of applications in the list.

    Trivial wrapper around len(), but exposing it as a named
    function gives the CLI a stable API. If we later decide
    to filter out test/dummy records, only this function
    changes, not every caller.
    """
    return len(apps)


def active_vs_closed(apps: list[Application]) -> dict[str, int]:
    """
    Split applications into active and closed counts.

    Uses Application.is_active() so the rule for "still alive"
    lives in one place (the model), not duplicated here. If
    GHOSTED is ever reclassified as active, only the model
    changes - this function picks up the new behaviour for free.
    """
    active = sum(1 for a in apps if a.is_active())
    closed = len(apps) - active
    return {"active": active, "closed": closed}
def status_breakdown(apps: list[Application]) -> dict[Status, int]:
    """
    Count of applications per status.

    Returns a dict keyed by Status enum (not raw strings),
    so the caller stays in the type-safe world. The CLI
    layer can format the keys however it likes for display.

    Statuses that don't appear in the input are simply absent
    from the dict - we don't pre-fill with zeros. The caller
    should treat "missing key" as "count of zero".
    """
    return dict(Counter(a.status for a in apps))


def source_breakdown(apps: list[Application]) -> dict[str, int]:
    """
    Count of applications per source (linkedin, referral, etc.).

    Source is a free-form string, not a constrained enum,
    so we use Counter directly without any normalization.
    Capitalization differences ("LinkedIn" vs "linkedin")
    would show as separate buckets - that's intentional;
    it surfaces inconsistencies in the user's input rather
    than silently merging them.
    """
    return dict(Counter(a.source for a in apps))

def response_rate(apps: list[Application]) -> float:
    """
    Percentage of applications that received any kind of response.

    "Response" means the status moved past APPLIED into anything
    that implies the employer engaged: ASSESSMENT, INTERVIEW,
    OFFER, REJECTED, WITHDRAWN. (WITHDRAWN counts because the
    user withdrew for a reason - typically progress past the
    initial application.)

    GHOSTED explicitly does NOT count - that status exists
    precisely to track non-responses.

    Returns a float between 0.0 and 100.0, rounded to one
    decimal place. Empty input returns 0.0 instead of raising
    a ZeroDivisionError - "no applications" should yield "no
    rate", not an exception.
    """
    if not apps:
        return 0.0

    response_statuses = {
        Status.ASSESSMENT,
        Status.INTERVIEW,
        Status.OFFER,
        Status.REJECTED,
        Status.WITHDRAWN,
    }
    responded = sum(1 for a in apps if a.status in response_statuses)
    rate = responded / len(apps) * 100
    return round(rate, 1)
def summary(apps: list[Application]) -> dict:
    """
    Combine every individual stat into one snapshot.

    This is a convenience wrapper for the CLI - one call,
    everything you need to print a complete `jobtrack stats`
    output. Each underlying function is still independently
    testable and reusable; this just bundles them.

    The returned dict uses string keys (not enums) for the
    top level, so it can be JSON-serialized cleanly if we
    ever expose stats over an API.
    """
    return {
        "total": total_count(apps),
        "active_vs_closed": active_vs_closed(apps),
        "status_breakdown": {
            status.value: count
            for status, count in status_breakdown(apps).items()
        },
        "source_breakdown": source_breakdown(apps),
        "response_rate": response_rate(apps),
    }