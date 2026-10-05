"""Rank scored jobs: match score, then company priority, then recency."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from .models import Job

PRIORITY_ORDER = {"A": 0, "B": 1, "C": 2}


def _priority(job: Job, priority_by_company: dict[str, str]) -> int:
    raw = priority_by_company.get(job.company_name, "C")
    return PRIORITY_ORDER.get(str(raw).upper(), 2)


def _posted_ts(job: Job) -> float:
    if not job.posted_date:
        return 0.0
    try:
        return datetime.fromisoformat(job.posted_date).timestamp()
    except ValueError:
        return 0.0


def rank_jobs(jobs: Iterable[Job],
              priority_by_company: Optional[dict[str, str]] = None) -> list[Job]:
    """Sort: match_score desc -> company priority (A first) -> newest posted."""
    prio = priority_by_company or {}

    def key(job: Job):
        score = job.match_score if job.match_score is not None else -1
        return (-score, _priority(job, prio), -_posted_ts(job))

    return sorted(jobs, key=key)


def select_relevant(jobs: Iterable[Job], minimum_match_score: int) -> list[Job]:
    """Jobs at or above the configured minimum match score."""
    return [j for j in jobs
            if j.match_score is not None and j.match_score >= minimum_match_score]


def is_high_match(job: Job, high_match_score: int) -> bool:
    return job.match_score is not None and job.match_score >= high_match_score
