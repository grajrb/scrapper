"""CLI entry point.

    python -m src.main discover
    python -m src.main scrape
    python -m src.main scrape --source greenhouse
    python -m src.main scrape --company "Company A"
    python -m src.main scrape --limit 10
    python -m src.main new
    python -m src.main export
    python -m src.main status
    python -m src.main errors
    python -m src.main test
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .adapters import available_sources, get_adapter_class
from .config import AppConfig, ConfigError, load_app_config
from .database import Database
from .exporters import export_all
from .logging_config import setup_logging
from .models import Company, RawJob, RunCounters, SearchQuery
from .ranking import rank_jobs
from .reporting import (
    format_errors,
    format_job_line,
    format_new_report,
    format_scrape_report,
    format_status_report,
)
from .services.job_service import JobService
from .services.notification_service import NotificationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description="Local-first job-search aggregation engine "
                    "(discovery only - never applies automatically).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("discover", help="Careers/ATS discovery (Phase 2 - not "
                                    "implemented yet)")

    p_scrape = sub.add_parser("scrape", help="Run the scrape pipeline")
    p_scrape.add_argument("-s", "--source", action="append",
                          help="only this source (repeatable); explicitly "
                               "requested sources run even if disabled")
    p_scrape.add_argument("-c", "--company",
                          help="only companies whose name contains this text")
    p_scrape.add_argument("-l", "--limit", type=int,
                          help="maximum number of companies to process")
    p_scrape.add_argument("-m", "--mode",
                          choices=["company", "board", "both"],
                          default="both",
                          help="company-mode adapters, board-mode adapters, "
                               "or both (default)")
    p_scrape.add_argument("--trigger", default="manual",
                          help=argparse.SUPPRESS)

    p_new = sub.add_parser("new", help="Show newly discovered jobs")
    p_new.add_argument("--hours", type=int,
                       help="only jobs first seen in the last N hours")

    p_export = sub.add_parser("export", help="Export jobs to CSV / Excel")
    p_export.add_argument("--format", choices=["csv", "xlsx", "both"],
                          default="both")
    p_export.add_argument("--out", help="output directory (default data/exports)")

    sub.add_parser("status", help="Show database and source status")

    p_errors = sub.add_parser("errors", help="Show recent scrape errors")
    p_errors.add_argument("--limit", type=int, default=20)

    sub.add_parser("test", help="Self-check without any network access")
    return parser


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_discover(args, cfg: AppConfig, db: Database) -> int:
    print("discover: career-page and ATS discovery is PHASE 2 and has not "
          "been implemented yet.\n"
          "Nothing was requested from the network. See README.md "
          "'Development strategy'.")
    return 0


def cmd_scrape(args, cfg: AppConfig, db: Database) -> int:
    service = JobService(cfg, db)
    counters, duration = service.run(
        sources=args.source or None,
        company=args.company,
        limit=args.limit,
        mode=args.mode,
        trigger=args.trigger or "manual",
    )
    report = format_scrape_report(counters, duration)
    print(report)

    priorities = {c.company_name: c.priority for c in db.get_companies()}
    ranked = rank_jobs(db.list_jobs(active_only=True), priorities)
    top = [j for j in ranked if j.match_score is not None][:10]
    if top:
        print("TOP MATCHES")
        for job in top:
            print(format_job_line(job))
        print()

    notifier = NotificationService(cfg.export_dir, db)
    notifier.notify("Scrape report", report)
    return 0


def cmd_new(args, cfg: AppConfig, db: Database) -> int:
    now = datetime.now(timezone.utc)
    last_run = db.get_last_run()
    if args.hours:
        since_dt = now - timedelta(hours=args.hours)
        since_label = f"last {args.hours}h"
    elif last_run:
        since_dt = datetime.fromisoformat(str(last_run["started_at"]))
        since_label = f"since run #{last_run['id']}"
    else:
        since_dt = now - timedelta(days=7)
        since_label = "last 7 days (no previous run)"
    since = since_dt.isoformat(timespec="seconds")

    all_jobs = db.list_jobs(active_only=False)
    new_jobs = sorted((j for j in all_jobs if j.first_seen > since),
                      key=lambda j: j.first_seen, reverse=True)
    day_ago = (now - timedelta(days=1)).isoformat(timespec="seconds")
    week_ago = (now - timedelta(days=7)).isoformat(timespec="seconds")

    print(format_new_report(
        new_jobs,
        new_since_run=db.count_new_since(since),
        new_24h=db.count_new_since(day_ago),
        new_7d=db.count_new_since(week_ago),
        since_label=since_label,
    ))
    return 0


def cmd_export(args, cfg: AppConfig, db: Database) -> int:
    out_dir = Path(args.out) if args.out else None
    written = export_all(db, cfg, fmt=args.format, out_dir=out_dir)
    if not written:
        print("Nothing exported (unknown format).")
        return 1
    print("EXPORTED")
    for path in written:
        print(f"  {path}")
    return 0


def cmd_status(args, cfg: AppConfig, db: Database) -> int:
    stats = db.get_stats()
    stats["db_path"] = str(db.path)
    print(format_status_report(stats, db.get_source_rows(), db.get_last_run()))
    return 0


def cmd_errors(args, cfg: AppConfig, db: Database) -> int:
    print(format_errors(db.get_errors(limit=max(1, args.limit))))
    return 0


def cmd_test(args, cfg: AppConfig, db: Database) -> int:
    """Offline self-check: no network requests are made."""
    failures: list[str] = []
    print("SELF CHECK (offline)")
    print(f"  config dir:      {cfg.config_dir}")
    print(f"  companies:       {len(cfg.companies)} "
          f"({len(cfg.enabled_companies)} enabled)")
    print(f"  configured sources: {len(cfg.sources)}")

    installed = available_sources()
    print(f"  installed adapters: {', '.join(installed) or '(none)'}")
    if not installed:
        failures.append("no adapters registered")

    for key, settings in cfg.sources.items():
        cls = get_adapter_class(key)
        state = "adapter OK" if cls else "no adapter (Phase 3/4)"
        if cls is not None:
            try:
                adapter = cls(settings=settings)
                health = adapter.health_check()
                state = f"health {'OK' if health.ok else 'FAILED'}: {health.detail}"
                if not health.ok:
                    failures.append(f"health check failed: {key}")
            except Exception as exc:
                state = f"error: {exc}"
                failures.append(f"adapter error: {key}")
        print(f"    - {key:<18}{state}")

    # smoke: normalize -> filter -> score -> rank (pure in-memory)
    try:
        from .filtering import JobFilter
        from .normalization import normalize_job
        from .scoring import score_job

        raw = RawJob(source="selftest", source_url="https://example.com/j/1",
                      payload={
                          "source_job_id": "t-1",
                          "company_name": (cfg.companies[0].company_name
                                           if cfg.companies else "Test Co"),
                          "title": "Backend Engineer",
                          "url": "https://example.com/j/1",
                          "location": (cfg.search.locations[0]
                                       if cfg.search.locations else "Remote"),
                          "skills": list(cfg.search.skills[:2]),
                          "experience_min": cfg.search.experience_min,
                          "experience_max": cfg.search.experience_max,
                          "employment_type": "Full-time",
                      })
        job = normalize_job(raw)
        job.target_company_match = job.company_name
        decision = JobFilter(cfg.search).evaluate(job)
        score = score_job(job, cfg.search)
        print(f"  smoke pipeline:  filter={'PASS' if decision.accepted else 'REJECT'}, "
              f"score={score.score}/100")
        if not decision.accepted:
            failures.append(f"smoke filter rejected sample job: {decision.notes}")
    except Exception as exc:
        failures.append(f"smoke pipeline crashed: {exc}")
        print(f"  smoke pipeline:  ERROR {exc}")

    stats = db.get_stats()
    print(f"  database:        {db.path} "
          f"({stats['jobs_total']} jobs, {stats['companies']} companies)")
    print()
    if failures:
        print("SELF CHECK FAILED:")
        for item in failures:
            print(f"  x {item}")
        return 1
    print("SELF CHECK PASSED (no network access was used)")
    return 0


_HANDLERS = {
    "discover": cmd_discover,
    "scrape": cmd_scrape,
    "new": cmd_new,
    "export": cmd_export,
    "status": cmd_status,
    "errors": cmd_errors,
    "test": cmd_test,
}


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging()

    try:
        cfg = load_app_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        with Database(cfg.db_path) as db:
            handler = _HANDLERS[args.command]
            return handler(args, cfg, db)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


