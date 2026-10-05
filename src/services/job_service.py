"""Pipeline orchestration.

Flow per run:
  adapters (discover/search/fetch) -> RawJob -> normalize -> target-company
  match -> dedup -> database -> filter -> score -> rank -> report/export

One failed company/source NEVER stops the run: every failure is caught,
logged to ``scrape_errors`` and the run continues.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from .adapters import create_adapter, get_adapter_class
from .config import AppConfig
from .database import Database
from .deduplication import Deduplicator, normalize_company_name
from .filtering import JobFilter
from .logging_config import get_logger
from .models import (
    AdapterResult,
    Company,
    Job,
    MatchConfidence,
    RawJob,
    ResultStatus,
    RunCounters,
    SearchMode,
    SearchQuery,
    utcnow_iso,
)
from .scoring import score_job

_STATUS_PRIORITY = {
    ResultStatus.OK: 0,
    ResultStatus.NOT_AVAILABLE: 1,
    ResultStatus.MANUAL_REVIEW: 2,
    ResultStatus.FAILED: 3,
}

_WORST_LABEL = {
    0: "OK",
    1: "NOT_AVAILABLE",
    2: "MANUAL_REVIEW",
    3: "FAILED",
}


def _domain_key(value: Optional[str]) -> str:
    text = (value or "").strip().casefold()
    for prefix in ("http://", "https://", "www."):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.split("/")[0].strip()


class JobService:
    """Runs the full scrape pipeline for the configured sources."""

    def __init__(self, cfg: AppConfig, db: Database):
        self.cfg = cfg
        self.db = db
        self.log = get_logger("job_service")
        self.job_filter = JobFilter(cfg.search)
        self.dedup = Deduplicator(db, new_status_days=cfg.search.new_status_days)
        self._companies_by_norm: dict[str, Company] = {}
        self._companies_by_domain: dict[str, Company] = {}
        self._evaluated_this_run: set[int] = set()
        self._rebuild_indexes()

    # -- setup -------------------------------------------------------------
    def _rebuild_indexes(self) -> None:
        self._companies_by_norm = {}
        self._companies_by_domain = {}
        for company in self.db.get_companies():
            norm = normalize_company_name(company.company_name)
            if norm:
                self._companies_by_norm.setdefault(norm, company)
            domain = _domain_key(company.company_domain)
            if domain:
                self._companies_by_domain.setdefault(domain, company)

    def _select_companies(self, company_name: Optional[str],
                          limit: Optional[int]) -> list[Company]:
        companies = [c for c in self.cfg.companies if c.enabled]
        if company_name:
            wanted = company_name.casefold()
            companies = [c for c in companies if wanted in c.company_name.casefold()]
        if limit:
            companies = companies[: max(0, int(limit))]
        return companies

    def _selected_sources(self, source_keys: Optional[list[str]],
                          mode: str) -> list[tuple[str, object]]:
        selected: list[tuple[str, object]] = []
        for key, settings in self.cfg.sources.items():
            if source_keys and key not in source_keys:
                continue
            explicit = bool(source_keys)
            if not settings.enabled and not explicit:
                continue
            cls = get_adapter_class(key)
            if cls is None:
                self.db.set_source_status(
                    key, "NOT_AVAILABLE",
                    error="No adapter installed yet (Phase 3/4)")
                self.log.info(
                    "Source '%s': enabled but no adapter installed - skipping "
                    "(nothing is faked).", key)
                continue
            if mode != "both" and str(cls.search_mode.value) != mode:
                continue
            selected.append((key, cls))
        return selected

    # -- public entry point ------------------------------------------------
    def run(self, sources: Optional[list[str]] = None,
            company: Optional[str] = None,
            limit: Optional[int] = None,
            mode: str = "both",
            trigger: str = "manual") -> tuple[RunCounters, float]:
        """Execute one scrape run. Returns (counters, duration_seconds)."""
        started = time.perf_counter()
        counters = RunCounters()
        self._evaluated_this_run = set()

        self.db.upsert_companies(self.cfg.companies)
        self._rebuild_indexes()
        self.db.ensure_sources(
            {key: self._source_type_value(key) for key in self.cfg.sources},
            enabled_keys={k for k, v in self.cfg.sources.items() if v.enabled})

        companies = self._select_companies(company, limit)
        counters.companies_total = len(companies)
        selected = self._selected_sources(sources, mode)
        counters.sources_selected = len(selected)

        if not selected:
            self.log.warning("No runnable sources selected "
                             "(check sources.yaml / installed adapters).")

        query = SearchQuery(
            roles=list(self.cfg.search.roles),
            locations=list(self.cfg.search.locations),
            countries=list(self.cfg.search.countries),
            experience_min=self.cfg.search.experience_min,
            experience_max=self.cfg.search.experience_max,
            company_name=company,
            limit=None,
        )

        run_id = self.db.start_run(trigger=trigger)
        self.log.info("Run #%s started: %d companies, %d source adapter(s)",
                      run_id, len(companies), len(selected))

        attempted: set[str] = set()
        failed: set[str] = set()
        outcome: dict[str, int] = {}
        jobs_per_source: dict[str, int] = {}

        for key, cls in selected:
            settings = self.cfg.sources[key]
            try:
                adapter = create_adapter(key, settings)
            except Exception as exc:
                self.log.error("Cannot instantiate adapter '%s': %s", key, exc)
                self.db.log_error(run_id, source=key, error_type="ADAPTER_INIT",
                                  message=str(exc))
                self.db.set_source_status(key, "FAILED", error=str(exc))
                counters.errors += 1
                continue

            health = adapter.health_check()
            if not health.ok:
                self.log.error("Health check failed for '%s': %s", key, health.detail)
                self.db.log_error(run_id, source=key, error_type="HEALTH",
                                  message=health.detail)
                self.db.set_source_status(key, "FAILED", error=health.detail)
                counters.errors += 1
                continue

            adapter_mode = adapter.search_mode
            if adapter_mode is SearchMode.BOARD:
                results = [self._safe_call(adapter.fetch_jobs, query, key, run_id)]
            else:
                results = []
                for company_obj in companies:
                    attempted.add(company_obj.company_name)
                    result = self._safe_call(adapter.fetch_jobs, company_obj,
                                             key, run_id)
                    if result.status is ResultStatus.FAILED and company_obj:
                        failed.add(company_obj.company_name)
                    results.append(result)

            counters.companies_processed = len(attempted)
            counters.companies_failed = len(failed)

            for result in results:
                self._process_result(result, adapter, run_id, counters,
                                     jobs_per_source)
                if result.status is ResultStatus.MANUAL_REVIEW:
                    counters.manual_review += 1
                elif result.status is ResultStatus.FAILED:
                    counters.errors += 1
                outcome[key] = max(outcome.get(key, 0),
                                   _STATUS_PRIORITY.get(result.status, 0))

            self.db.set_source_status(
                key, _WORST_LABEL.get(outcome.get(key, 0), "OK"),
                jobs_found_delta=jobs_per_source.get(key, 0),
                error=(self._last_reason(results) if outcome.get(key, 0) >= 2
                       else None))
            counters.sources_processed += 1
            self.log.info("Source '%s': %s (%d raw job(s))", key,
                          _WORST_LABEL.get(outcome.get(key, 0), "OK"),
                          jobs_per_source.get(key, 0))

        # Jobs not seen for inactive_after_days become INACTIVE (never deleted).
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=self.cfg.search.inactive_after_days))
        deactivated = self.db.mark_stale_inactive(
            cutoff.isoformat(timespec="seconds"))
        if deactivated:
            self.log.info("Marked %d job(s) INACTIVE (not seen for %d days)",
                          deactivated, self.cfg.search.inactive_after_days)

        self.db.finish_run(run_id, counters.to_dict())
        duration = time.perf_counter() - started
        self.log.info("Run #%s finished in %.2fs", run_id, duration)
        return counters, duration

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _source_type_value(key: str) -> str:
        from .models import source_type
        return source_type(key).value

    @staticmethod
    def _last_reason(results: list[AdapterResult]) -> Optional[str]:
        for result in reversed(results):
            if result.reason:
                return result.reason
        return None

    def _safe_call(self, fn, target, key: str, run_id: int) -> AdapterResult:
        """Call an adapter method; never let an exception kill the run."""
        try:
            result = fn(target)
            if not isinstance(result, AdapterResult):
                raise TypeError(f"{fn.__name__} returned {type(result).__name__}, "
                                "expected AdapterResult")
            return result
        except Exception as exc:  # broad on purpose: isolate failures
            company_name = getattr(target, "company_name", None)
            self.log.error("Source '%s' failed for %s: %s",
                           key, company_name or "query", exc)
            self.db.log_error(run_id, source=key, company=company_name,
                              error_type=type(exc).__name__, message=str(exc))
            return AdapterResult(source=key, status=ResultStatus.FAILED,
                                 company=company_name,
                                 reason=str(exc),
                                 recommended_action="Not retried "
                                 "automatically; check logs for details.")

    def _process_result(self, result: AdapterResult, adapter, run_id: int,
                        counters: RunCounters,
                        jobs_per_source: dict[str, int]) -> None:
        source = result.source or adapter.source_key

        if result.status is ResultStatus.MANUAL_REVIEW:
            self.db.log_error(run_id, source=source, company=result.company,
                              url=result.url, error_type="MANUAL_REVIEW",
                              message=result.reason or "manual review required")
            self.log.warning("MANUAL_REVIEW [%s] %s - %s", source,
                             result.company or "", result.reason or "")
            return

        if result.status is ResultStatus.FAILED:
            self.db.log_error(run_id, source=source, company=result.company,
                              url=result.url, error_type="FAILED",
                              message=result.reason or "unknown failure")
            self.log.error("FAILED [%s] %s - %s", source,
                           result.company or "", result.reason or "")
            return

        if result.status is ResultStatus.NOT_AVAILABLE:
            self.log.info("NOT_AVAILABLE [%s]: %s", source, result.reason or "")
            return

        jobs_per_source[source] = jobs_per_source.get(source, 0) + len(result.jobs)
        counters.jobs_found += len(result.jobs)
        for raw in result.jobs:
            try:
                self._ingest(raw, adapter, counters)
            except Exception as exc:
                self.log.error("Ingest failed in '%s': %s", source, exc)
                self.db.log_error(run_id, source=source,
                                  error_type="INGEST", message=str(exc))
                counters.errors += 1

    # -- job ingestion -----------------------------------------------------
    def _ingest(self, raw: RawJob, adapter, counters: RunCounters) -> None:
        # Company mode: the company context is authoritative for matching.
        company_ctx = None
        if adapter.search_mode is SearchMode.COMPANY:
            hint = raw.company_hint or raw.payload.get("company_name")
            norm = normalize_company_name(hint)
            company_ctx = self._companies_by_norm.get(norm)

        job = adapter.normalize(raw, company=company_ctx)
        self._attach_target(job, raw, company_ctx)

        outcome = self.dedup.resolve(job)
        job.id = outcome.job_id
        if outcome.is_new:
            counters.new_jobs += 1
        else:
            counters.duplicates += 1
            if outcome.promoted or outcome.data_changed:
                counters.updated_jobs += 1
        if job.target_company_match:
            self.db.set_job_target_match(
                job.id, job.target_company_match,
                job.match_confidence or MatchConfidence.NONE.value)

        # Evaluate each canonical job at most once per run so duplicate
        # records do not double-count filters/high-match stats.
        if job.id in self._evaluated_this_run:
            return
        self._evaluated_this_run.add(job.id)

        decision = self.job_filter.evaluate(job)
        if not decision.accepted:
            counters.filtered_out += 1
            self.log.debug("Filtered [%s] %s - %s", job.source, job.title,
                           decision.reason or "")
            return

        score = score_job(job, self.cfg.search)
        job.match_score = score.score
        job.match_reasons = score.reasons
        job.match_warnings = score.warnings
        self.db.update_job_score(job.id, score.score, score.reasons,
                                 score.warnings)
        if score.score >= self.cfg.search.high_match_score:
            counters.high_match += 1
        if score.score < self.cfg.search.minimum_match_score:
            counters.below_threshold += 1

    def _attach_target(self, job: Job, raw: RawJob,
                       company_ctx: Optional[Company]) -> None:
        """Associate the job with a target company (Phase 1: exact match).

        Phase 5 adds fuzzy matching; here only exact normalized names and
        exact domains are used so unrelated companies never merge.
        """
        if company_ctx is not None:
            job.target_company_match = company_ctx.company_name
            job.match_confidence = MatchConfidence.HIGH.value
            job.company_id = job.company_id or company_ctx.id
            return

        norm = normalize_company_name(job.company_name)
        match = self._companies_by_norm.get(norm)
        if match is None:
            domain = _domain_key(raw.payload.get("company_domain")) \
                or _domain_key(_host_of(job.source_url or job.canonical_url))
            if domain:
                match = self._companies_by_domain.get(domain)
        if match is not None:
            job.target_company_match = match.company_name
            job.match_confidence = MatchConfidence.HIGH.value
            job.company_id = job.company_id or match.id
        else:
            job.target_company_match = None
            job.match_confidence = MatchConfidence.NONE.value


def _host_of(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        from urllib.parse import urlsplit
        return urlsplit(url).netloc or None
    except ValueError:
        return None



