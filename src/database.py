"""SQLite persistence layer.

Schema covers all phases: companies, sources, jobs, job_sources,
scrape_runs, scrape_errors, ats_discovery, notifications - with indexes
on company, title, location, posted_date, match_score, canonical_url
and source_job_id.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import Company, Job, JobStatus, utcnow_iso

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS companies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name  TEXT NOT NULL,
    company_domain TEXT,
    careers_url   TEXT,
    priority      TEXT NOT NULL DEFAULT 'B',
    enabled       INTEGER NOT NULL DEFAULT 1,
    ats           TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_name
    ON companies (company_name);

CREATE TABLE IF NOT EXISTS sources (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key     TEXT NOT NULL UNIQUE,
    source_type    TEXT,
    enabled        INTEGER NOT NULL DEFAULT 1,
    status         TEXT NOT NULL DEFAULT 'UNKNOWN',
    last_run_at    TEXT,
    last_success_at TEXT,
    last_error     TEXT,
    jobs_found     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_key TEXT NOT NULL UNIQUE,
    company_id    INTEGER,
    company_name  TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL,
    source_job_id TEXT,
    title         TEXT NOT NULL DEFAULT '',
    canonical_url TEXT,
    source_url    TEXT,
    location      TEXT,
    country       TEXT,
    city          TEXT,
    remote_status TEXT NOT NULL DEFAULT 'unknown',
    employment_type TEXT,
    department    TEXT,
    experience_min INTEGER,
    experience_max INTEGER,
    description   TEXT,
    skills        TEXT NOT NULL DEFAULT '[]',
    salary_min    REAL,
    salary_max    REAL,
    salary_currency TEXT,
    posted_date   TEXT,
    updated_date  TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    ats           TEXT,
    raw_data_hash TEXT,
    status        TEXT NOT NULL DEFAULT 'NEW',
    target_company_match TEXT,
    match_confidence TEXT,
    match_score   INTEGER,
    match_reasons TEXT NOT NULL DEFAULT '[]',
    match_warnings TEXT NOT NULL DEFAULT '[]',
    is_fixture    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source        TEXT NOT NULL,
    source_job_id TEXT NOT NULL DEFAULT '',
    source_url    TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    times_seen    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'RUNNING',
    trigger       TEXT NOT NULL DEFAULT 'manual',
    counters      TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS scrape_errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER,
    source      TEXT,
    company     TEXT,
    url         TEXT,
    error_type  TEXT NOT NULL,
    http_status INTEGER,
    message     TEXT,
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ats_discovery (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id   INTEGER,
    company_name TEXT NOT NULL,
    careers_url  TEXT,
    ats          TEXT,
    confidence   TEXT,
    status       TEXT,
    jobs_url     TEXT,
    discovered_at TEXT NOT NULL,
    UNIQUE (company_name)
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    channel    TEXT NOT NULL,
    subject    TEXT,
    body       TEXT,
    status     TEXT NOT NULL DEFAULT 'PENDING'
);

CREATE INDEX IF NOT EXISTS idx_jobs_company      ON jobs (company_name);
CREATE INDEX IF NOT EXISTS idx_jobs_title        ON jobs (title);
CREATE INDEX IF NOT EXISTS idx_jobs_location     ON jobs (location);
CREATE INDEX IF NOT EXISTS idx_jobs_posted       ON jobs (posted_date);
CREATE INDEX IF NOT EXISTS idx_jobs_score        ON jobs (match_score);
CREATE INDEX IF NOT EXISTS idx_jobs_canonical    ON jobs (canonical_url);
CREATE INDEX IF NOT EXISTS idx_jobs_source_jid   ON jobs (source_job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status       ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen   ON jobs (first_seen);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen    ON jobs (last_seen);
CREATE INDEX IF NOT EXISTS idx_job_sources_job   ON job_sources (job_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_job_sources_uniq
    ON job_sources (job_id, source, source_job_id);
CREATE INDEX IF NOT EXISTS idx_errors_run        ON scrape_errors (run_id);
CREATE INDEX IF NOT EXISTS idx_runs_started      ON scrape_runs (started_at);
"""

def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def job_from_row(row: sqlite3.Row) -> Job:
    """Convert a ``jobs`` table row into a :class:`Job`."""
    def _json(value: Optional[str], default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default

    data = dict(row)
    return Job(
        id=data["id"],
        company_name=data["company_name"] or "",
        company_id=data["company_id"],
        source=data["source"] or "",
        source_job_id=data["source_job_id"],
        title=data["title"] or "",
        canonical_url=data["canonical_url"],
        source_url=data["source_url"],
        location=data["location"],
        country=data["country"],
        city=data["city"],
        remote_status=data["remote_status"] or "unknown",
        employment_type=data["employment_type"],
        department=data["department"],
        experience_min=data["experience_min"],
        experience_max=data["experience_max"],
        description=data["description"],
        skills=_json(data["skills"], []),
        salary_min=data["salary_min"],
        salary_max=data["salary_max"],
        salary_currency=data["salary_currency"],
        posted_date=data["posted_date"],
        updated_date=data["updated_date"],
        first_seen=data["first_seen"],
        last_seen=data["last_seen"],
        is_active=bool(data["is_active"]),
        ats=data["ats"],
        raw_data_hash=data["raw_data_hash"],
        status=data["status"],
        content_hash=data["canonical_key"],
        target_company_match=data["target_company_match"],
        match_confidence=data["match_confidence"],
        match_score=data["match_score"],
        match_reasons=_json(data["match_reasons"], []),
        match_warnings=_json(data["match_warnings"], []),
        is_fixture=bool(data["is_fixture"]),
    )


class Database:
    """Thin wrapper around one SQLite connection."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        try:
            self.conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error:  # pragma: no cover - e.g. network drive
            pass
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA_SQL)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, tuple(params))

    # -- companies ---------------------------------------------------------
    def upsert_companies(self, companies: list[Company]) -> dict[str, int]:
        """Insert or update companies; returns {company_name: id}."""
        now = utcnow_iso()
        ids: dict[str, int] = {}
        with self.conn:
            for company in companies:
                row = self._execute(
                    "SELECT id FROM companies WHERE company_name = ?",
                    (company.company_name,),
                ).fetchone()
                if row:
                    cid = int(row["id"])
                    self._execute(
                        "UPDATE companies SET company_domain=?, careers_url=?, "
                        "priority=?, enabled=?, ats=COALESCE(?, ats), updated_at=? "
                        "WHERE id=?",
                        (company.company_domain, company.careers_url,
                         company.priority, int(company.enabled), company.ats,
                         now, cid),
                    )
                else:
                    cur = self._execute(
                        "INSERT INTO companies (company_name, company_domain, "
                        "careers_url, priority, enabled, ats, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (company.company_name, company.company_domain,
                         company.careers_url, company.priority,
                         int(company.enabled), company.ats, now, now),
                    )
                    cid = int(cur.lastrowid)
                ids[company.company_name] = cid
        return ids

    def prune_companies(self, keep_names: list[str]) -> dict[str, int]:
        """Remove companies no longer present in the config CSV.

        Companies still referenced by jobs are disabled instead of deleted
        so job history and foreign keys stay intact (jobs are never deleted
        just because a company or listing disappeared).

        Returns {"deleted": n, "disabled": m}.
        """
        keep = {n for n in keep_names}
        deleted = 0
        disabled = 0
        if keep:
            sql = ("SELECT id FROM companies WHERE company_name NOT IN ("
                   + ",".join("?" * len(keep)) + ")")
            params: tuple = tuple(keep)
        else:  # empty config = clear everything stale
            sql = "SELECT id FROM companies"
            params = ()
        with self.conn:
            stale = self._execute(sql, params).fetchall()
            for row in stale:
                cid = int(row["id"])
                has_jobs = self._execute(
                    "SELECT 1 FROM jobs WHERE company_id = ? LIMIT 1",
                    (cid,),
                ).fetchone()
                if has_jobs:
                    self._execute(
                        "UPDATE companies SET enabled = 0, updated_at = ? "
                        "WHERE id = ?",
                        (utcnow_iso(), cid),
                    )
                    disabled += 1
                else:
                    self._execute("DELETE FROM companies WHERE id = ?", (cid,))
                    deleted += 1
        return {"deleted": deleted, "disabled": disabled}


    def get_companies(self, enabled_only: bool = False) -> list[Company]:
        sql = "SELECT * FROM companies"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY priority, company_name"
        rows = self._execute(sql).fetchall()
        return [
            Company(
                id=int(r["id"]),
                company_name=r["company_name"],
                company_domain=r["company_domain"],
                careers_url=r["careers_url"],
                priority=r["priority"],
                enabled=bool(r["enabled"]),
                ats=r["ats"],
            )
            for r in rows
        ]

    def get_company_rows(self) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT company_name, company_domain, careers_url, priority, "
            "enabled, ats FROM companies ORDER BY priority, company_name"
        ).fetchall()
        return [dict(r) for r in rows]

    # -- sources -----------------------------------------------------------
    def ensure_sources(self, source_types: dict[str, str],
                       enabled_keys: set[str] | None = None) -> None:
        """Register configured sources so ``status`` can show them."""
        enabled_keys = enabled_keys if enabled_keys is not None else set(source_types)
        with self.conn:
            for key, stype in source_types.items():
                self._execute(
                    "INSERT INTO sources (source_key, source_type, enabled, status) "
                    "VALUES (?, ?, ?, 'UNKNOWN') "
                    "ON CONFLICT(source_key) DO UPDATE SET "
                    "source_type=excluded.source_type, enabled=excluded.enabled",
                    (key, stype, int(key in enabled_keys)),
                )

    def set_source_status(self, key: str, status: str,
                          jobs_found_delta: int = 0,
                          error: Optional[str] = None) -> None:
        now = utcnow_iso()
        with self.conn:
            self._execute(
                "INSERT INTO sources (source_key, status, last_run_at, last_success_at, "
                "last_error, jobs_found) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source_key) DO UPDATE SET "
                "status=excluded.status, last_run_at=excluded.last_run_at, "
                "last_success_at=CASE WHEN excluded.status='OK' "
                "THEN excluded.last_success_at ELSE sources.last_success_at END, "
                "last_error=excluded.last_error, "
                "jobs_found=sources.jobs_found + excluded.jobs_found",
                (key, status, now, now if status == "OK" else None,
                 error, int(jobs_found_delta)),
            )

    def get_source_rows(self) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT source_key, source_type, enabled, status, last_run_at, "
            "last_success_at, last_error, jobs_found FROM sources ORDER BY source_key"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_source_row(self, key: str) -> Optional[dict[str, Any]]:
        row = self._execute("SELECT * FROM sources WHERE source_key=?",
                            (key,)).fetchone()
        return dict(row) if row else None

    # -- scrape runs -------------------------------------------------------
    def start_run(self, trigger: str = "manual") -> int:
        with self.conn:
            cur = self._execute(
                "INSERT INTO scrape_runs (started_at, status, trigger) "
                "VALUES (?, 'RUNNING', ?)", (utcnow_iso(), trigger))
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, counters: dict[str, Any],
                   status: str = "COMPLETED") -> None:
        with self.conn:
            self._execute(
                "UPDATE scrape_runs SET finished_at=?, status=?, counters=? WHERE id=?",
                (utcnow_iso(), status, json.dumps(counters), run_id))

    def get_last_run(self) -> Optional[dict[str, Any]]:
        row = self._execute(
            "SELECT * FROM scrape_runs WHERE status != 'RUNNING' "
            "ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["counters"] = json.loads(data.get("counters") or "{}")
        except ValueError:
            data["counters"] = {}
        return data

    # -- errors ------------------------------------------------------------
    def log_error(self, run_id: Optional[int], source: Optional[str] = None,
                  company: Optional[str] = None, url: Optional[str] = None,
                  error_type: str = "ERROR", message: str = "",
                  http_status: Optional[int] = None) -> None:
        with self.conn:
            if error_type == "MANUAL_REVIEW":
                # MANUAL_REVIEW is a *status*, not an event: keep exactly one
                # row per (source, company) so repeated runs do not inflate
                # scrape_errors with identical records.
                self._execute(
                    "DELETE FROM scrape_errors "
                    "WHERE error_type = 'MANUAL_REVIEW' "
                    "AND (source IS ?) AND (company IS ?)",
                    (source, company))
            self._execute(
                "INSERT INTO scrape_errors (run_id, source, company, url, "
                "error_type, http_status, message, occurred_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, source, company, url, error_type, http_status,
                 message, utcnow_iso()))

    def prune_stale_manual_review(self, keep_names: list[str]) -> int:
        """Drop MANUAL_REVIEW rows for companies no longer in the config.

        Source-level rows (company IS NULL) are always kept. Returns the
        number of rows removed.
        """
        keep = {n for n in keep_names}
        if keep:
            sql = ("DELETE FROM scrape_errors "
                   "WHERE error_type = 'MANUAL_REVIEW' "
                   "AND company IS NOT NULL "
                   "AND company NOT IN ("
                   + ",".join("?" * len(keep)) + ")")
            params: tuple = tuple(keep)
        else:
            sql = ("DELETE FROM scrape_errors "
                   "WHERE error_type = 'MANUAL_REVIEW' "
                   "AND company IS NOT NULL")
            params = ()
        with self.conn:
            cur = self._execute(sql, params)
            return int(cur.rowcount or 0)

    def get_errors(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM scrape_errors ORDER BY id DESC LIMIT ?",
            (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    def count_errors(self) -> int:
        row = self._execute("SELECT COUNT(*) AS n FROM scrape_errors").fetchone()
        return int(row["n"])

    # -- ats discovery (schema ready; populated from Phase 2 onwards) ------
    def save_ats_discovery(self, company_name: str, careers_url: Optional[str],
                           ats: Optional[str], confidence: Optional[str],
                           status: str, jobs_url: Optional[str] = None) -> None:
        with self.conn:
            self._execute(
                "INSERT INTO ats_discovery (company_name, careers_url, ats, "
                "confidence, status, jobs_url, discovered_at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(company_name) DO UPDATE SET careers_url=excluded.careers_url, "
                "ats=excluded.ats, confidence=excluded.confidence, "
                "status=excluded.status, jobs_url=excluded.jobs_url, "
                "discovered_at=excluded.discovered_at",
                (company_name, careers_url, ats, confidence, status, jobs_url,
                 utcnow_iso()))

    def get_ats_rows(self) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT company_name, careers_url, ats, confidence, status, jobs_url, "
            "discovered_at FROM ats_discovery ORDER BY company_name").fetchall()
        return [dict(r) for r in rows]

    # -- jobs: lookup ------------------------------------------------------
    def find_job_id_by_source(self, source: str,
                              source_job_id: str) -> Optional[int]:
        """Find a canonical job via any of its source references."""
        row = self._execute(
            "SELECT job_id FROM job_sources WHERE source=? AND source_job_id=? "
            "ORDER BY job_id LIMIT 1",
            (source, source_job_id or "")).fetchone()
        if row:
            return int(row["job_id"])
        row = self._execute(
            "SELECT id FROM jobs WHERE source=? AND source_job_id=? LIMIT 1",
            (source, source_job_id)).fetchone()
        return int(row["id"]) if row else None

    def find_job_id_by_url(self, canonical_url: str) -> Optional[int]:
        if not canonical_url:
            return None
        row = self._execute(
            "SELECT id FROM jobs WHERE canonical_url=? LIMIT 1",
            (canonical_url,)).fetchone()
        if row:
            return int(row["id"])
        row = self._execute(
            "SELECT job_id AS id FROM job_sources WHERE source_url=? LIMIT 1",
            (canonical_url,)).fetchone()
        return int(row["id"]) if row else None

    def find_job_id_by_hash(self, content_hash: str) -> Optional[int]:
        if not content_hash:
            return None
        row = self._execute(
            "SELECT id FROM jobs WHERE canonical_key=? LIMIT 1",
            (content_hash,)).fetchone()
        return int(row["id"]) if row else None

    def get_job(self, job_id: int) -> Optional[Job]:
        row = self._execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return job_from_row(row) if row else None

    # -- jobs: write -------------------------------------------------------
    def insert_job(self, job: Job) -> int:
        """Insert a new canonical job (content_hash must be unique)."""
        now = utcnow_iso()
        key = job.content_hash or job.raw_data_hash or f"new-{now}"
        with self.conn:
            cur = self._execute(
                "INSERT INTO jobs (canonical_key, company_id, company_name, source, "
                "source_job_id, title, canonical_url, source_url, location, country, "
                "city, remote_status, employment_type, department, experience_min, "
                "experience_max, description, skills, salary_min, salary_max, "
                "salary_currency, posted_date, updated_date, first_seen, last_seen, "
                "is_active, ats, raw_data_hash, status, target_company_match, "
                "match_confidence, match_score, match_reasons, match_warnings, "
                "is_fixture, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                "?,?,?,?,?,?,?)",
                (key, job.company_id, job.company_name, job.source,
                 job.source_job_id, job.title, job.canonical_url, job.source_url,
                 job.location, job.country, job.city, job.remote_status,
                 job.employment_type, job.department, job.experience_min,
                 job.experience_max, job.description,
                 json.dumps(job.skills or []), job.salary_min, job.salary_max,
                 job.salary_currency, job.posted_date, job.updated_date,
                 job.first_seen, job.last_seen, int(job.is_active), job.ats,
                 job.raw_data_hash, job.status, job.target_company_match,
                 job.match_confidence, job.match_score,
                 json.dumps(job.match_reasons or []),
                 json.dumps(job.match_warnings or []),
                 int(job.is_fixture), now, now))
            return int(cur.lastrowid)

    def touch_job(self, job_id: int, seen_at: Optional[str] = None,
                  new_status_days: int = 7) -> str:
        """Update last_seen; age NEW -> SEEN after new_status_days."""
        now = seen_at or utcnow_iso()
        with self.conn:
            row = self._execute(
                "SELECT status, first_seen FROM jobs WHERE id=?",
                (job_id,)).fetchone()
            if not row:
                return ""
            status = row["status"]
            if status == JobStatus.NEW.value:
                first = _parse_iso(row["first_seen"])
                now_dt = _parse_iso(now)
                if first and now_dt and (now_dt - first) > timedelta(days=new_status_days):
                    status = JobStatus.SEEN.value
            self._execute(
                "UPDATE jobs SET last_seen=?, status=?, updated_at=? WHERE id=?",
                (now, status, now, job_id))
            return status

    def promote_job_source(self, job_id: int, job: Job) -> None:
        """Switch the canonical source when a higher-priority one appears."""
        with self.conn:
            self._execute(
                "UPDATE jobs SET source=?, source_job_id=?, source_url=?, "
                "canonical_url=?, updated_at=? WHERE id=?",
                (job.source, job.source_job_id, job.source_url,
                 job.canonical_url or job.source_url, utcnow_iso(), job_id))

    def update_job_score(self, job_id: int, score: int,
                         reasons: list[str], warnings: list[str]) -> None:
        with self.conn:
            self._execute(
                "UPDATE jobs SET match_score=?, match_reasons=?, match_warnings=?, "
                "updated_at=? WHERE id=?",
                (int(score), json.dumps(reasons), json.dumps(warnings),
                 utcnow_iso(), job_id))

    def set_job_target_match(self, job_id: int, company_name: Optional[str],
                             confidence: str) -> None:
        with self.conn:
            self._execute(
                "UPDATE jobs SET target_company_match=?, match_confidence=?, "
                "updated_at=? WHERE id=?",
                (company_name, confidence, utcnow_iso(), job_id))

    def add_job_source(self, job_id: int, source: str,
                       source_job_id: Optional[str], source_url: Optional[str]) -> None:
        """Record/refresh one source reference of a canonical job."""
        now = utcnow_iso()
        sid = source_job_id or ""
        with self.conn:
            row = self._execute(
                "SELECT id FROM job_sources WHERE job_id=? AND source=? "
                "AND source_job_id=?",
                (job_id, source, sid)).fetchone()
            if row:
                self._execute(
                    "UPDATE job_sources SET last_seen=?, times_seen=times_seen+1, "
                    "source_url=COALESCE(?, source_url) WHERE id=?",
                    (now, source_url, int(row["id"])))
            else:
                self._execute(
                    "INSERT INTO job_sources (job_id, source, source_job_id, "
                    "source_url, first_seen, last_seen, times_seen) "
                    "VALUES (?,?,?,?,?,?,1)",
                    (job_id, source, sid, source_url, now, now))

    def get_job_sources(self, job_id: int) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT source, source_job_id, source_url, first_seen, last_seen, "
            "times_seen FROM job_sources WHERE job_id=? ORDER BY id",
            (job_id,)).fetchall()
        return [dict(r) for r in rows]

    # -- jobs: queries -----------------------------------------------------
    def list_jobs(self, active_only: bool = True,
                  status: Optional[str] = None,
                  min_score: Optional[int] = None) -> list[Job]:
        sql = "SELECT * FROM jobs WHERE 1=1"
        params: list[Any] = []
        if active_only:
            sql += " AND is_active=1"
        if status:
            sql += " AND status=?"
            params.append(status)
        if min_score is not None:
            sql += " AND match_score>=?"
            params.append(min_score)
        sql += " ORDER BY match_score DESC NULLS LAST, company_name, title"
        rows = self._execute(sql, params).fetchall()
        return [job_from_row(r) for r in rows]

    def count_jobs(self, active_only: bool = True) -> int:
        sql = "SELECT COUNT(*) AS n FROM jobs"
        if active_only:
            sql += " WHERE is_active=1"
        return int(self._execute(sql).fetchone()["n"])

    def count_by_status(self) -> dict[str, int]:
        rows = self._execute(
            "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
        return {r["status"]: int(r["n"]) for r in rows}

    def count_new_since(self, since_iso: str) -> int:
        row = self._execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE first_seen > ?",
            (since_iso,)).fetchone()
        return int(row["n"])

    def mark_stale_inactive(self, cutoff_iso: str) -> int:
        """Mark jobs not seen since cutoff as INACTIVE (never delete rows)."""
        with self.conn:
            cur = self._execute(
                "UPDATE jobs SET is_active=0, status='INACTIVE', updated_at=? "
                "WHERE last_seen < ? AND status NOT IN ('INACTIVE','EXPIRED')",
                (utcnow_iso(), cutoff_iso))
            return int(cur.rowcount)

    def get_stats(self) -> dict[str, Any]:
        total = self.count_jobs(active_only=False)
        active = self.count_jobs(active_only=True)
        now = datetime.now(timezone.utc)
        day_ago = (now - timedelta(days=1)).isoformat(timespec="seconds")
        week_ago = (now - timedelta(days=7)).isoformat(timespec="seconds")
        row = self._execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE first_seen > ?", (day_ago,)).fetchone()
        new_24h = int(row["n"])
        row = self._execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE first_seen > ?", (week_ago,)).fetchone()
        new_7d = int(row["n"])
        row = self._execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE is_active=1 AND match_score IS NOT NULL"
        ).fetchone()
        scored = int(row["n"])
        row = self._execute(
            "SELECT COUNT(*) AS n FROM job_sources").fetchone()
        source_refs = int(row["n"])
        return {
            "jobs_total": total,
            "jobs_active": active,
            "jobs_new_24h": new_24h,
            "jobs_new_7d": new_7d,
            "jobs_scored": scored,
            "job_source_refs": source_refs,
            "companies": int(self._execute(
                "SELECT COUNT(*) AS n FROM companies").fetchone()["n"]),
            "companies_enabled": int(self._execute(
                "SELECT COUNT(*) AS n FROM companies WHERE enabled=1").fetchone()["n"]),
            "sources": int(self._execute(
                "SELECT COUNT(*) AS n FROM sources").fetchone()["n"]),
            "errors": self.count_errors(),
            "by_status": self.count_by_status(),
        }





