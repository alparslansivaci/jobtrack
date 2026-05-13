"""
Data models.

Three types here:
  - Status: the stages an application can be in (enum)
  - Application: a single internship / job application record
  - MatchResult: the output of CV-to-job-description matching

We use Pydantic v2. extra='forbid' is intentional - when we
read back from the DB, an unknown column should raise loudly,
not get silently swallowed. (This differs from a public API
client, where 'ignore' is usually right because we don't
control the source.)
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Status(str, Enum):
    """
    Lifecycle stages of an application.

    Inheriting from str (in addition to Enum) is deliberate:
    when SQLite serializes the value, it writes "applied"
    instead of "Status.APPLIED". Pydantic also serializes
    these straight to strings in JSON.

    Ordering is roughly by frequency. GHOSTED isn't an
    official term, but it reflects reality - we want to
    track applications that simply never got a response.
    """

    APPLIED = "applied"
    ASSESSMENT = "assessment"   
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"     
    GHOSTED = "ghosted"         


class Application(BaseModel):
    """
    A single internship / job application record.

    Field design decisions:
      - id: optional because we don't know it when creating
        a new record - the DB assigns it. It's populated
        when we read an existing row back.
      - applied_at vs. last_status_change: the first is
        fixed at creation, the second updates on every
        status change. Keeping them separate lets us
        cleanly answer "how long have I been waiting in
        this state?".
      - notes: free-form. Things like "talked to recruiter
        Anna, interview on Tuesday".
      - job_description: stored as raw text so the TF-IDF
        match can be re-computed any time, against a new CV.
    """

    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    company: str
    role: str
    source: str = "linkedin"
    status: Status = Status.APPLIED
    applied_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_status_change: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    job_url: str | None = None
    job_description: str | None = None
    notes: str | None = None

    def days_since_applied(self) -> int:
        """Days elapsed since the application was submitted. Used in stats."""
        delta = datetime.now(timezone.utc) - self.applied_at
        return delta.days

    def days_in_current_status(self) -> int:
        """How long we've been in the current status. Used for ghost detection."""
        delta = datetime.now(timezone.utc) - self.last_status_change
        return delta.days

    def is_active(self) -> bool:
        """
        Is this application still "live"?

        REJECTED, WITHDRAWN, GHOSTED are considered closed.
        Everything else is in flight. Used in stats to split
        active vs. closed counts.
        """
        terminal = {Status.REJECTED, Status.WITHDRAWN, Status.GHOSTED}
        return self.status not in terminal


class MatchResult(BaseModel):
    """
    Result of comparing a CV against a job description.

    score: a value between 0 and 10, higher means better fit.
    Under the hood TF-IDF cosine similarity returns 0-1; we
    scale by 10 to make output more readable.

    Why two keyword lists (missing + strong)? A bare score
    isn't actionable. "You got 8.2" tells me nothing concrete.
    "kubernetes and docker are missing, python and sql are
    strong" gives the user a direction to act on.
    """

    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0.0, le=10.0)
    missing_keywords: list[str] = Field(default_factory=list)
    strong_matches: list[str] = Field(default_factory=list)

    def grade(self) -> str:
        """
        Translate the score into a short human-readable label.
        Used in CLI output for quick visual feedback.

        Thresholds aren't arbitrary - TF-IDF cosine of 0.5 is
        already quite high in practice, because two texts
        rarely live in the same narrow subspace. They share
        a wide vocabulary universe instead.
        """
        if self.score >= 7.5:
            return "Strong match"
        if self.score >= 5.0:
            return "Decent match"
        if self.score >= 2.5:
            return "Weak match"
        return "Poor match"
