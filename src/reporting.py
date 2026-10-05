"""Terminal reports for scrape runs, status, errors and new-job views."""
from __future__ import annotations

from typing import Any, Optional

from .models import Job, RunCounters

_RULE = "=" * 54


def _line(label: str, value: Any) -> str:
    return f"{label:<24}{value}"


def format_scrape_report(counters: RunCounters | dict,
                         duration: float) -> str:
    c = counters.to_dict() if isinstance(counters, RunCounters) else counters
    lines = [
        _RULE,
        "SCRAPE COMPLETE",
        _RULE,
        _line("Companies:", f"{c.get('companies_total', 0)}"),
        _line("Processed:", c.get("companies_processed", 0)),
        _line("Failed:", c.get("companies_failed", 0)),
        _line("Sources selected:", c.get("sources_selected", 0)),
        _line("Sources processed:", c.get("sources_processed", 0)),
        _line("Sources no adapter:", c.get("sources_not_available", 0)),
        _line("Jobs found:", f"{c.get('jobs_found', 0):,}"),
        _line("New:", f"{c.get('new_jobs', 0):,}"),
        _line("Updated:", f"{c.get('updated_jobs', 0):,}"),
        _line("Duplicates:", f"{c.get('duplicates', 0):,}"),
        _line("Filtered out:", f"{c.get('filtered_out', 0):,}"),
        _line("Below score threshold:", c.get("below_threshold", 0)),
        _line("High match:", c.get("high_match", 0)),
        _line("Manual review:", c.get("manual_review", 0)),
        _line("Errors:", c.get("errors", 0)),
        _line("Duration:", f"{duration:.2f}s"),
        _RULE,
    ]
    return "\n".join(lines)


def format_job_line(job: Job) -> str:
    score = f"{job.match_score:>3}" if job.match_score is not None else "  -"
    fixture = " [FIXTURE]" if job.is_fixture else ""
    return (f"  {score}/100  {job.company_name} - {job.title} "
            f"({job.location or 'location?'}{fixture})")


def format_status_report(stats: dict[str, Any],
                         source_rows: list[dict[str, Any]],
                         last_run: Optional[dict[str, Any]]) -> str:
    lines = [_RULE, "STATUS", _RULE]
    lines.append(_line("Database:", stats.get("db_path", "")))
    lines.append(_line("Companies:", f"{stats.get('companies', 0)} "
                                     f"({stats.get('companies_enabled', 0)} enabled)"))
    lines.append(_line("Jobs (active):", f"{stats.get('jobs_active', 0):,}"))
    lines.append(_line("Jobs (total):", f"{stats.get('jobs_total', 0):,}"))
    lines.append(_line("New in last 24h:", stats.get("jobs_new_24h", 0)))
    lines.append(_line("New in last 7d:", stats.get("jobs_new_7d", 0)))
    lines.append(_line("Source references:", stats.get("job_source_refs", 0)))
    lines.append(_line("Errors logged:", stats.get("errors", 0)))
    by_status = stats.get("by_status") or {}
    if by_status:
        lines.append(_line("By status:",
                           ", ".join(f"{k}={v}"
                                     for k, v in sorted(by_status.items()))))
    if last_run:
        lines.append(_line("Last run:",
                           f"#{last_run.get('id')} {last_run.get('started_at')} "
                           f"({last_run.get('status')})"))
    lines.append("")
    lines.append(f"{'SOURCE':<18}{'STATUS':<16}{'JOBS':<8}LAST RUN")
    lines.append("-" * 54)
    for row in source_rows:
        enabled = "" if row.get("enabled") else " (disabled)"
        lines.append(
            f"{row.get('source_key', ''):<18}"
            f"{str(row.get('status', '')) + enabled:<16}"
            f"{str(row.get('jobs_found', 0)):<8}"
            f"{row.get('last_run_at') or '-'}")
    lines.append(_RULE)
    return "\n".join(lines)


def format_errors(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No errors recorded."
    lines = [f"{'WHEN':<21}{'SOURCE':<16}{'TYPE':<16}{'COMPANY':<20}MESSAGE",
             "-" * 100]
    for row in rows:
        message = str(row.get("message") or "")[:60]
        lines.append(
            f"{str(row.get('occurred_at', ''))[:19]:<21}"
            f"{str(row.get('source') or '-'):<16}"
            f"{str(row.get('error_type') or '-'):<16}"
            f"{str(row.get('company') or '-'):<20}{message}")
    return "\n".join(lines)


def format_new_report(new_jobs: list[Job], new_since_run: int,
                      new_24h: int, new_7d: int,
                      since_label: str) -> str:
    lines = [
        _RULE,
        "NEW JOBS",
        _RULE,
        _line("New since last run:", f"{new_since_run} ({since_label})"),
        _line("New in last 24 hours:", new_24h),
        _line("New in last 7 days:", new_7d),
        _RULE,
    ]
    if not new_jobs:
        lines.append("No new jobs to show.")
    else:
        for job in new_jobs[:100]:
            lines.append(format_job_line(job))
        if len(new_jobs) > 100:
            lines.append(f"  ... and {len(new_jobs) - 100} more "
                         "(see exports for the full list)")
    return "\n".join(lines)
