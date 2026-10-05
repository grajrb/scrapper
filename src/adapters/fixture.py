"""Fixture adapter (source key: ``fixture``) - LOCAL TEST DATA ONLY.

Loads fabricated jobs from ``data/raw/fixture_jobs.json`` so the whole
pipeline (normalize -> dedup -> store -> filter -> score -> rank -> export)
can be exercised and tested completely offline.

IMPORTANT: the data is fake. Every job produced here is flagged
``is_fixture`` in the database and exports, and this adapter is DISABLED
by default in ``config/sources.yaml``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from ..models import (
    AdapterResult,
    Company,
    RawJob,
    ResultStatus,
    SearchMode,
    SearchQuery,
    SourceType,
)
from .base import SourceAdapter, register

_DEFAULT_PATH = (Path(__file__).resolve().parent.parent.parent
                 / "data" / "raw" / "fixture_jobs.json")


def load_fixture_jobs(path: Path | None = None) -> list[RawJob]:
    file_path = Path(path) if path else _DEFAULT_PATH
    if not file_path.exists():
        raise FileNotFoundError(f"Fixture data not found: {file_path}")
    data = json.loads(file_path.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or []
    raw_jobs = []
    for entry in jobs:
        payload = dict(entry)
        source = str(payload.pop("source", "fixture"))
        url = payload.pop("url", None)
        payload.setdefault("url", url)
        raw_jobs.append(RawJob(source=source, payload=payload, source_url=url,
                               company_hint=payload.get("company_name")))
    return raw_jobs


@register
class FixtureAdapter(SourceAdapter):
    """Board-mode adapter serving clearly labeled local test data."""

    source_key = "fixture"
    source_type = SourceType.JOB_BOARD
    search_mode = SearchMode.BOARD
    is_test_source = True

    def __init__(self, settings=None, http_client=None):
        super().__init__(settings=settings, http_client=http_client)
        data_path = (self.settings.extra.get("path")
                     if self.settings else None)
        self.data_path = Path(data_path) if data_path else _DEFAULT_PATH

    def discover(self, company: Company) -> AdapterResult:
        return self.not_available(
            "The fixture adapter only works in board mode.", company=company.company_name)

    def search(self, query: SearchQuery) -> AdapterResult:
        try:
            jobs = load_fixture_jobs(self.data_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return AdapterResult(source=self.source_key,
                                 status=ResultStatus.FAILED,
                                 reason=f"Fixture data unreadable: {exc}")
        if query and query.company_name:
            wanted = query.company_name.casefold()
            jobs = [j for j in jobs
                    if wanted in str(j.payload.get("company_name", "")).casefold()]
        if query and query.limit:
            jobs = jobs[: int(query.limit)]
        self.logger.warning(
            "FIXTURE MODE: serving %d locally generated TEST jobs (not real).",
            len(jobs))
        return AdapterResult(source=self.source_key, status=ResultStatus.OK,
                             jobs=jobs,
                             detail="local fixture test data - not real jobs")

    def fetch_jobs(self, target: Union[Company, SearchQuery]) -> AdapterResult:
        if isinstance(target, SearchQuery):
            return self.search(target)
        return self.discover(target)

    def health_check(self):
        from ..models import HealthStatus
        if self.data_path.exists():
            return HealthStatus(self.source_key, True,
                                f"fixture file present: {self.data_path.name}")
        return HealthStatus(self.source_key, False,
                            f"fixture file missing: {self.data_path}")
