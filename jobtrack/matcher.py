"""
matcher.py — TF-IDF based CV / job description matching.

Why TF-IDF and not an LLM embedding?

  - Determinism: same input always returns the same score, which
    makes the function testable with exact assertions.
  - Privacy: the CV and job descriptions never leave the machine.
    No API key, no third-party call.
  - Cost & latency: runs in milliseconds locally. No rate limit,
    no quota.

The trade-off is real: TF-IDF matches surface tokens, so
"ML engineer" and "machine learning engineer" don't align.
For a personal tool that's an acceptable limitation, documented
here rather than hidden.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from jobtrack.models import Application, MatchResult
# Domain-specific stop words: words that appear frequently in both
# CVs and job postings but carry no signal about skill match. The
# default English stop-words list catches grammar words; this list
# catches recruiting/HR jargon. Curated by hand from real postings —
# extend it as new noise words show up.
_JOB_STOP_WORDS = frozenset({
    "experience", "experienced", "looking", "required", "requirements",
    "skilled", "skills", "engineer", "developer", "candidate",
    "preferred", "ability", "able", "work", "working", "role",
    "team", "company", "join", "responsible", "responsibilities",
    "year", "years", "strong", "proven", "knowledge", "understanding",
})

def match_score(cv_text: str, job_description: str, top_n: int = 5) -> MatchResult:
    """
    Compare a CV against a job description and return a structured
    match result.

    Why top_n? The two keyword lists are meant for human consumption,
    not exhaustive auditing. 3-5 items is the sweet spot: enough to
    be informative, few enough to scan in a glance.

    Args:
        cv_text: Plain text of the CV.
        job_description: Plain text of the job posting.
        top_n: How many keywords to surface in each list.

    Returns:
        MatchResult with score (0-10), strong_matches, missing_keywords.
    """
    # Guard against empty input. Without this, TfidfVectorizer raises
    # an opaque ValueError ("empty vocabulary"); we'd rather return a
    # clean zero-result.
    if not cv_text.strip() or not job_description.strip():
        return MatchResult(score=0.0, missing_keywords=[], strong_matches=[])

    # Build the vectorizer. stop_words='english' filters out "the",
    # "and", "of" etc. before TF-IDF even sees them - cleaner vocab,
    # better signal. lowercase=True is the default; we make it explicit
    # because matching is case-insensitive and that should be obvious
    # from the code, not assumed.
    # Combine scikit-learn's English list with our domain-specific
    # list. The vectorizer accepts a list (not a string) when we
    # want a custom set.
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    combined_stop_words = list(ENGLISH_STOP_WORDS | _JOB_STOP_WORDS)
    vectorizer = TfidfVectorizer(stop_words=combined_stop_words, lowercase=True)

    # fit_transform on BOTH documents together. Critical: if we called
    # fit_transform on each separately, their IDFs would come from
    # different vocabularies and the vectors wouldn't be comparable.
    # Shape after this: (2, vocab_size) - two rows, one per document.
    matrix = vectorizer.fit_transform([cv_text, job_description])

    # cosine_similarity returns a 2x2 matrix; we want the off-diagonal
    # cell [0, 1] which is "doc 0 vs doc 1". The diagonal is always 1
    # (each doc compared with itself).
    similarity = cosine_similarity(matrix[0], matrix[1])[0][0]

    # Scale 0-1 to 0-10 for the public-facing model. Round to one
    # decimal at the presentation boundary, same principle as stats.py.
    score = round(similarity * 10, 1)

    # Extract per-word TF-IDF arrays for each document. .toarray()
    # converts the sparse matrix to a dense numpy array so we can
    # index into it with normal Python.
    feature_names = vectorizer.get_feature_names_out()
    cv_vector = matrix[0].toarray()[0]
    job_vector = matrix[1].toarray()[0]

    # Strong matches: words with non-zero TF-IDF in BOTH documents,
    # ranked by their importance in the job description (because the
    # job is what the user is trying to align to).
    strong = [
        feature_names[i]
        for i in job_vector.argsort()[::-1]
        if cv_vector[i] > 0 and job_vector[i] > 0
    ][:top_n]

    # Missing keywords: words important in the job description but
    # absent from the CV. argsort()[::-1] gives indices from highest
    # to lowest TF-IDF.
    missing = [
        feature_names[i]
        for i in job_vector.argsort()[::-1]
        if cv_vector[i] == 0 and job_vector[i] > 0
    ][:top_n]

    return MatchResult(
        score=score,
        strong_matches=strong,
        missing_keywords=missing,
    )
def rank_jobs(
    cv_text: str,
    applications: list[Application],
) -> list[tuple[Application, MatchResult]]:
    """
    Score the CV against every application that has a job description,
    and return them sorted from best match to worst.

    Why vectorize everything together instead of looping match_score?
    A single fit on [cv] + all job descriptions gives every pair the
    same vocabulary and IDF. Looping match_score would refit per pair,
    producing scores from different feature spaces — the ranking
    wouldn't be strictly comparable across rows.

    Applications without a job_description are silently skipped, not
    scored at zero. A missing description is "unknown", not "bad".

    Args:
        cv_text: Plain text of the CV.
        applications: List of Application objects, some of which may
            have job_description=None.

    Returns:
        List of (Application, MatchResult) tuples, sorted by score
        descending. Applications without a job_description are absent.
    """
    # Filter out applications with no description. We do this BEFORE
    # vectorizing so the index alignment between input docs and output
    # vectors stays clean.
    scorable = [a for a in applications if a.job_description]

    # Two empty-result paths: no CV text, or no applications to score.
    if not cv_text.strip() or not scorable:
        return []

    # Build the vectorizer with the same stop-words setup as match_score.
    # We deliberately repeat this rather than share state — keeps the two
    # functions independent and testable in isolation.
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    combined_stop_words = list(ENGLISH_STOP_WORDS | _JOB_STOP_WORDS)
    vectorizer = TfidfVectorizer(stop_words=combined_stop_words, lowercase=True)

    # Documents in order: CV first (index 0), then every job description.
    # The order matters because we index into the matrix below.
    documents = [cv_text] + [a.job_description for a in scorable]
    matrix = vectorizer.fit_transform(documents)

    # Compare CV (row 0) against every job description (rows 1..N).
    # cosine_similarity returns a 2D array shape (1, N); we flatten to 1D.
    cv_row = matrix[0]
    job_rows = matrix[1:]
    similarities = cosine_similarity(cv_row, job_rows)[0]

    # Build a MatchResult per application. We don't recompute strong/missing
    # keywords here — rank is about the overall comparison; detailed
    # keyword analysis is what match_score is for. If the CLI needs
    # keywords for the top hit, it can call match_score on that one pair.
    feature_names = vectorizer.get_feature_names_out()
    cv_vector = cv_row.toarray()[0]

    results: list[tuple[Application, MatchResult]] = []
    for app, similarity, job_row in zip(scorable, similarities, job_rows):
        score = round(similarity * 10, 1)
        job_vector = job_row.toarray()[0]

        # Same logic as match_score but inlined to avoid a second
        # fit_transform call.
        strong = [
            feature_names[i]
            for i in job_vector.argsort()[::-1]
            if cv_vector[i] > 0 and job_vector[i] > 0
        ][:5]
        missing = [
            feature_names[i]
            for i in job_vector.argsort()[::-1]
            if cv_vector[i] == 0 and job_vector[i] > 0
        ][:5]

        results.append((
            app,
            MatchResult(score=score, strong_matches=strong, missing_keywords=missing),
        ))

    # Sort by score descending. Stable sort: ties preserve original order,
    # which means insertion order from the DB query (typically by id or
    # date) breaks ties predictably.
    results.sort(key=lambda pair: pair[1].score, reverse=True)
    return results