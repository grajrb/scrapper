"""Cross-source deduplication.

Match keys, tried in order:
1. (source, source_job_id) - exact reference already recorded
2. normalized canonical URL - same link despite tracking parameters
3. deterministic content hash - company + title + location + experience

Canonical source priority: official career page > official ATS > job board.
All source references are preserved in the ``job_sources`` table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .database import Database
from .models import Job, source_tier
from .normalization import normalize_url, sha256_text

_WS = re.compile(r"\s+")
_LEGAL_SUFFIXES = re.compile(
    r"\b(pvt|private|limited|ltd|inc|llc|llp|corp|corporation|co|company|"
    r"gmbh|ag|sa|bv|nv|plc|group|india)\b")


def normalize_company_name(name: Optional[str]) -> str:
    """Aggressive-but-safe normalization for company-name matching.

    Lowercases, strips punctuation and common legal suffixes, collapses
    whitespace. Deliberately does NOT stem words (e.g. 'technologies' and
    'tech' stay different) to avoid merging unrelated companies.
    """
    text = (name or "").casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = _LEGAL_SUFFIXES.sub(" ", text)
    return _WS.sub(" ", text).strip()


def content_hash(job: Job) -> str:
    """Deterministic identity of a job posting across sources."""
    parts = "|".join([
        normalize_company_name(job.company_name),
        _WS.sub(" ", (job.title or "").casefold()).strip(),
        _WS.sub(" ", (job.location or "").casefold()).strip(),
        str(job.experience_min if job.experience_min is not None else ""),
        str(job.experience_max if job.experience_max is not None else ""),
    ])
    return sha256_text(parts)


@dataclass
class DedupOutcome:
    """Result of resolving one incoming job against the database."""
    outcome: str                      # "new" | "duplicate"
    job_id: int
    promoted: bool = False            # canonical source was upgraded
    existing: Optional[Job] = None    # canonical job (duplicates only)
    data_changed: bool = False        # duplicate arrived with different data

    @property
    def is_new(self) -> bool:
        return self.outcome == "new"


class Deduplicator:
    """Resolves incoming normalized jobs against stored canonical jobs."""

    def __init__(self, db: Database, new_status_days: int = 7):
        self.db = db
        self.new_status_days = new_status_days

    def resolve(self, job: Job) -> DedupOutcome:
        job.content_hash = content_hash(job)
        canonical_url = job.canonical_url or normalize_url(job.source_url)

        existing_id: Optional[int] = None
        if job.source_job_id:
            existing_id = self.db.find_job_id_by_source(job.source,
                                                        job.source_job_id)
        if existing_id is None and canonical_url:
            existing_id = self.db.find_job_id_by_url(canonical_url)
        if existing_id is None:
            existing_id = self.db.find_job_id_by_hash(job.content_hash)

        if existing_id is None:
            job_id = self.db.insert_job(job)
            self.db.add_job_source(job_id, job.source, job.source_job_id,
                                   job.source_url)
            return DedupOutcome("new", job_id)

        existing = self.db.get_job(existing_id)
        self.db.touch_job(existing_id, seen_at=job.last_seen,
                          new_status_days=self.new_status_days)
        self.db.add_job_source(existing_id, job.source, job.source_job_id,
                               job.source_url)

        promoted = False
        data_changed = False
        if existing:
            if source_tier(job.source) < source_tier(existing.source):
                self.db.promote_job_source(existing_id, job)
                promoted = True
            if (existing.posted_date != job.posted_date
                    or existing.description != job.description
                    or existing.skills != job.skills):
                data_changed = True

        return DedupOutcome("duplicate", existing_id, promoted=promoted,
                            existing=existing, data_changed=data_changed)
