"""Source adapter interface + plugin registry.

Every source (career page, ATS, job board) is one module in this package
that subclasses :class:`SourceAdapter` and decorates itself with
:func:`register`. The core application only talks to this interface -
it never contains source-specific logic.

CANONICAL RAW PAYLOAD SCHEMA
----------------------------
``SourceAdapter.normalize`` (or the default normalizer) must map
website-specific fields into this payload so the core stays generic:

    source_job_id   str|None   unique id within the source
    company_name    str        posting company
    company_domain  str|None
    title           str        job title
    url             str        application / detail URL
    location        str|None   free text, e.g. "Bangalore, India"
    city            str|None   set only if the source states it
    country         str|None   set only if the source states it
    remote_status   str|None   remote | hybrid | onsite
    employment_type str|None   e.g. "Full-time"
    department      str|None
    experience_min  int|None   years
    experience_max  int|None   years
    description     str|None
    skills          list[str]|str|None
    salary_min      float|None
    salary_max      float|None
    salary_currency str|None
    posted_date     str|int|None  (parseable date; ISO preferred)
    updated_date    str|int|None
    ats             str|None   ATS provider if known

Never invent values - leave unknown fields out or ``None``.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from ..config import SourceSettings
from ..models import (
    AdapterResult,
    Company,
    HealthStatus,
    Job,
    RawJob,
    ResultStatus,
    SearchMode,
    SearchQuery,
    SourceType,
)

_REGISTRY: dict[str, type["SourceAdapter"]] = {}


def register(cls: type["SourceAdapter"]) -> type["SourceAdapter"]:
    """Class decorator that adds an adapter to the plugin registry."""
    key = getattr(cls, "source_key", "")
    if not key:
        raise ValueError(f"{cls.__name__} must define a non-empty source_key")
    _REGISTRY[key] = cls
    return cls


def available_sources() -> list[str]:
    return sorted(_REGISTRY)


def get_adapter_class(key: str) -> Optional[type["SourceAdapter"]]:
    return _REGISTRY.get(key)


def create_adapter(key: str,
                   settings: Optional[SourceSettings] = None,
                   http_client: Any = None) -> "SourceAdapter":
    """Instantiate a registered adapter (raises KeyError if unknown)."""
    cls = _REGISTRY.get(key)
    if cls is None:
        raise KeyError(f"No adapter registered for source '{key}'")
    return cls(settings=settings, http_client=http_client)


class SourceAdapter(ABC):
    """Common interface implemented by every source adapter."""

    source_key: str = ""
    source_type: SourceType = SourceType.OTHER
    search_mode: SearchMode = SearchMode.BOARD
    is_test_source: bool = False

    def __init__(self, settings: Optional[SourceSettings] = None,
                 http_client: Any = None):
        self.settings = settings or SourceSettings(key=self.source_key)
        self.http = http_client
        self.logger = logging.getLogger(
            f"jobsearch.adapter.{self.source_key or self.__class__.__name__}")

    # -- interface ---------------------------------------------------------
    @abstractmethod
    def discover(self, company: Company) -> AdapterResult:
        """Company mode: discover the careers page/ATS and return its jobs."""

    @abstractmethod
    def search(self, query: SearchQuery) -> AdapterResult:
        """Board mode: run one search query and return raw jobs."""

    @abstractmethod
    def fetch_jobs(self, target: Company | SearchQuery) -> AdapterResult:
        """Entry point used by the pipeline (company or query depending on mode)."""

    def normalize(self, raw: RawJob, company: Optional[Company] = None,
                  company_id: Optional[int] = None) -> Job:
        """RawJob -> Job. Default uses the canonical payload; override only
        for source-specific quirks."""
        from ..normalization import normalize_job
        return normalize_job(raw, company=company, company_id=company_id)

    def health_check(self) -> HealthStatus:
        """Cheap availability probe; default assumes OK (no network)."""
        return HealthStatus(self.source_key, True, "OK (no probe configured)")

    # -- helpers for subclasses -------------------------------------------
    def manual_review(self, reason: str, url: Optional[str] = None,
                      company: Optional[str] = None,
                      action: Optional[str] = None) -> AdapterResult:
        """Mark this source for manual review WITHOUT bypassing any rule."""
        return AdapterResult(
            source=self.source_key,
            status=ResultStatus.MANUAL_REVIEW,
            url=url,
            company=company,
            reason=reason,
            recommended_action=action or (
                "Open the URL in a browser, review the postings manually, "
                "and do not automate this source."),
        )

    def not_available(self, reason: str,
                      company: Optional[str] = None) -> AdapterResult:
        return AdapterResult(source=self.source_key,
                             status=ResultStatus.NOT_AVAILABLE,
                             company=company, reason=reason)
