"""Core data models shared by every layer of the job-search engine.

Adapters produce :class:`RawJob` records (with a canonical raw payload),
the normalizer turns them into :class:`Job` records, and everything else
(dedup, filtering, scoring, export) only ever sees :class:`Job`.

Nothing in this module knows about any specific website or ATS.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Optional


def utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    SEEN = "SEEN"
    INACTIVE = "INACTIVE"
    EXPIRED = "EXPIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    FAILED = "FAILED"


class SourceStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    OK = "OK"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    DISABLED = "DISABLED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class SourceType(str, Enum):
    COMPANY_CAREERS = "company_careers"
    ATS = "ats"
    JOB_BOARD = "job_board"
    OTHER = "other"


class RemoteStatus(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class ResultStatus(str, Enum):
    """Status carried by an AdapterResult."""
    OK = "OK"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    FAILED = "FAILED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class SearchMode(str, Enum):
    COMPANY = "company"   # adapter runs once per target company
    BOARD = "board"       # adapter runs once per search query


class MatchConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class MatchLevel(str, Enum):
    """Granular outcome used by filtering/scoring helpers."""
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Source tiers: 1 = official career page, 2 = official ATS, 3 = job board
# ---------------------------------------------------------------------------

ATS_SOURCES = frozenset({
    "greenhouse", "lever", "workday", "ashby", "smartrecruiters", "icims",
    "taleo", "jobvite", "bamboohr", "recruitee", "teamtailor",
    "successfactors",
})

BOARD_SOURCES = frozenset({
    "indeed", "hirist", "naukri", "linkedin",
})

COMPANY_PAGE_SOURCES = frozenset({"company_careers", "generic"})

# Sources that only ever serve local test data (never real postings).
TEST_SOURCES = frozenset({"fixture", "fixture_web"})


def source_tier(source: str) -> int:
    """Canonical-source priority: 1 = career page, 2 = ATS, 3 = job board."""
    s = (source or "").lower()
    if s in COMPANY_PAGE_SOURCES:
        return 1
    if s in ATS_SOURCES:
        return 2
    return 3


def source_type(source: str) -> SourceType:
    s = (source or "").lower()
    if s in COMPANY_PAGE_SOURCES:
        return SourceType.COMPANY_CAREERS
    if s in ATS_SOURCES:
        return SourceType.ATS
    if s in BOARD_SOURCES:
        return SourceType.JOB_BOARD
    return SourceType.OTHER


def best_application_url(job: "Job",
                         alternates: Iterable[tuple[str, str]] = ()) -> Optional[str]:
    """Return the best available application URL.

    Priority: official company career page -> official ATS -> job board.
    Never submits anything; this is only a link for the user.
    """
    candidates: list[tuple[str, Optional[str]]] = [(job.source, job.source_url)]
    candidates.extend((src, url) for src, url in alternates)
    scored: list[tuple[int, int, str]] = []
    for idx, (src, url) in enumerate(candidates):
        if url:
            scored.append((source_tier(src), idx, url))
    if scored:
        scored.sort(key=lambda t: (t[0], t[1]))
        return scored[0][2]
    return job.canonical_url


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Company:
    company_name: str
    company_domain: Optional[str] = None
    careers_url: Optional[str] = None
    priority: str = "B"
    enabled: bool = True
    id: Optional[int] = None
    ats: Optional[str] = None


@dataclass
class RawJob:
    """A job exactly as returned by a source adapter.

    ``payload`` must follow the CANONICAL RAW PAYLOAD SCHEMA documented in
    :mod:`src.adapters.base` so the core normalizer never needs to know
    source-specific field names.
    """
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    source_url: Optional[str] = None
    company_hint: Optional[str] = None
    discovered_at: str = field(default_factory=utcnow_iso)


@dataclass
class Job:
    """Normalized job - the single common format produced by every adapter."""

    company_name: str = ""
    company_id: Optional[int] = None
    source: str = ""
    source_job_id: Optional[str] = None
    title: str = ""
    canonical_url: Optional[str] = None
    source_url: Optional[str] = None
    location: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    remote_status: str = RemoteStatus.UNKNOWN.value
    employment_type: Optional[str] = None
    department: Optional[str] = None
    experience_min: Optional[int] = None
    experience_max: Optional[int] = None
    description: Optional[str] = None
    skills: list[str] = field(default_factory=list)
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    posted_date: Optional[str] = None
    updated_date: Optional[str] = None
    first_seen: str = field(default_factory=utcnow_iso)
    last_seen: str = field(default_factory=utcnow_iso)
    is_active: bool = True
    ats: Optional[str] = None
    raw_data_hash: Optional[str] = None
    # --- pipeline fields (not part of the wire format, stored alongside) ---
    status: str = JobStatus.NEW.value
    content_hash: Optional[str] = None
    target_company_match: Optional[str] = None
    match_confidence: Optional[str] = MatchConfidence.NONE.value
    match_score: Optional[int] = None
    match_reasons: list[str] = field(default_factory=list)
    match_warnings: list[str] = field(default_factory=list)
    is_fixture: bool = False
    id: Optional[int] = None

    @property
    def experience_display(self) -> str:
        if self.experience_min is None and self.experience_max is None:
            return "Not listed"
        lo = "?" if self.experience_min is None else str(self.experience_min)
        hi = "?" if self.experience_max is None else str(self.experience_max)
        return f"{lo}-{hi} yrs"

    @property
    def application_url(self) -> Optional[str]:
        """Best application URL (career page > ATS > job board)."""
        return best_application_url(self)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdapterResult:
    """Uniform result returned by every adapter operation."""
    source: str
    status: ResultStatus = ResultStatus.OK
    jobs: list[RawJob] = field(default_factory=list)
    url: Optional[str] = None
    company: Optional[str] = None
    reason: Optional[str] = None
    recommended_action: Optional[str] = None
    detail: Optional[str] = None

    @property
    def is_manual_review(self) -> bool:
        return self.status is ResultStatus.MANUAL_REVIEW


@dataclass
class HealthStatus:
    source: str
    ok: bool
    detail: str = "OK"


@dataclass
class SearchQuery:
    """Board-mode query built from search_config.yaml."""
    roles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    experience_min: Optional[int] = None
    experience_max: Optional[int] = None
    company_name: Optional[str] = None
    limit: Optional[int] = None


@dataclass
class RunCounters:
    """Counters reported at the end of a scrape run."""
    companies_total: int = 0
    companies_processed: int = 0
    companies_failed: int = 0
    sources_selected: int = 0
    sources_processed: int = 0
    sources_not_available: int = 0
    jobs_found: int = 0
    new_jobs: int = 0
    updated_jobs: int = 0
    duplicates: int = 0
    filtered_out: int = 0
    below_threshold: int = 0
    high_match: int = 0
    manual_review: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def job_to_json(job: Job) -> str:
    """Serialize a Job for debugging / raw metadata storage."""
    return json.dumps(job.to_dict(), ensure_ascii=False, sort_keys=True, default=str)


