"""Tests for the SQLite layer: schema, indexes, CRUD, new-job tracking."""
from src.database import Database, job_from_row
from src.models import Company, Job, utcnow_iso

EXPECTED_TABLES = {
    "companies", "sources", "jobs", "job_sources", "scrape_runs",
    "scrape_errors", "ats_discovery", "notifications",
}

EXPECTED_INDEXES = {
    "idx_jobs_company", "idx_jobs_title", "idx_jobs_location",
    "idx_jobs_posted", "idx_jobs_score", "idx_jobs_canonical",
    "idx_jobs_source_jid",
}


def _table_names(db):
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def _index_names(db):
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    return {r["name"] for r in rows}


def test_schema_creates_all_tables(db):
    assert EXPECTED_TABLES <= _table_names(db)


def test_schema_creates_required_indexes(db):
    assert EXPECTED_INDEXES <= _index_names(db)


def test_upsert_companies_idempotent(db):
    companies = [Company("Acme Cloud", "acmecloud.example", None, "A", True),
                 Company("Nimbus Data", "nimbusdata.example", None, "B", True)]
    ids1 = db.upsert_companies(companies)
    ids2 = db.upsert_companies(companies)
    assert ids1 == ids2
    assert len(db.get_companies()) == 2
    assert len(db.get_companies(enabled_only=True)) == 2


def test_disabled_company_flag(db):
    db.upsert_companies([Company("Hidden Co", enabled=False)])
    assert len(db.get_companies()) == 1
    assert len(db.get_companies(enabled_only=True)) == 0


def test_prune_companies_removes_stale_and_disables_referenced(db):
    ids = db.upsert_companies([
        Company("Acme Cloud", "acmecloud.example", None, "A", True),
        Company("Ghost Co", None, None, "B", True),
        Company("Phantom Co", None, None, "C", True),
    ])
    _insert_sample(db, company_id=ids["Ghost Co"])  # job keeps Ghost alive

    result = db.prune_companies(["Acme Cloud"])

    assert result == {"deleted": 1, "disabled": 1}
    remaining = {c.company_name: c for c in db.get_companies()}
    assert set(remaining) == {"Acme Cloud", "Ghost Co"}
    assert remaining["Acme Cloud"].enabled is True
    assert remaining["Ghost Co"].enabled is False  # history preserved
    # the job itself was never touched
    assert db.count_jobs(active_only=False) == 1


def test_manual_review_rows_are_deduped_per_source_company(db):
    for _ in range(3):  # simulate three identical runs
        db.log_error(None, source="generic", company="Acme Cloud",
                     error_type="MANUAL_REVIEW",
                     message="No careers URL configured")
    db.log_error(None, source="generic", company="Nimbus Data",
                 error_type="MANUAL_REVIEW", message="No careers URL")
    db.log_error(None, source="indeed", company=None,
                 error_type="MANUAL_REVIEW", message="Blocks automation")
    for _ in range(2):  # real errors keep their history
        db.log_error(None, source="lever", error_type="ERROR",
                     message="timeout after 20s")

    errors = db.get_errors(limit=100)
    mr = [e for e in errors if e["error_type"] == "MANUAL_REVIEW"]
    real = [e for e in errors if e["error_type"] == "ERROR"]
    assert len(mr) == 3        # 2 company-level + 1 source-level, no copies
    assert len(real) == 2      # event-style errors are not deduped


def test_prune_stale_manual_review_keeps_source_rows(db):
    db.log_error(None, source="generic", company="Ghost Co",
                 error_type="MANUAL_REVIEW", message="stale")
    db.log_error(None, source="generic", company="Acme Cloud",
                 error_type="MANUAL_REVIEW", message="kept")
    db.log_error(None, source="indeed", company=None,
                 error_type="MANUAL_REVIEW", message="source-level")

    removed = db.prune_stale_manual_review(["Acme Cloud"])

    assert removed == 1
    remaining = {(e["source"], e["company"]) for e in db.get_errors(100)}
    assert ("generic", "Acme Cloud") in remaining
    assert ("indeed", None) in remaining          # source-level survives
    assert ("generic", "Ghost Co") not in remaining


def _insert_sample(db, **overrides) -> Job:
    fields = dict(
        company_name="Acme Cloud", source="fixture", source_job_id="fx-1",
        title="Backend Engineer",
        canonical_url="https://acme.example/j/1",
        source_url="https://acme.example/j/1",
        location="Bangalore, India", content_hash="hash-1",
        posted_date="2026-10-01",
    )
    fields.update(overrides)
    job = Job(**fields)
    job.id = db.insert_job(job)
    db.add_job_source(job.id, job.source, job.source_job_id, job.source_url)
    return job


def test_insert_and_lookup_job(db):
    job = _insert_sample(db)
    assert job.id is not None
    assert db.find_job_id_by_url("https://acme.example/j/1") == job.id
    assert db.find_job_id_by_hash("hash-1") == job.id
    assert db.find_job_id_by_source("fixture", "fx-1") == job.id
    loaded = db.get_job(job.id)
    assert loaded is not None
    assert loaded.title == "Backend Engineer"
    assert loaded.content_hash == "hash-1"


def test_job_sources_unique_and_counts(db):
    job = _insert_sample(db)
    db.add_job_source(job.id, "fixture", "fx-1", "https://acme.example/j/1")
    db.add_job_source(job.id, "fixture", "fx-1", "https://acme.example/j/1")
    refs = db.get_job_sources(job.id)
    assert len(refs) == 1
    assert refs[0]["times_seen"] == 3


def test_job_from_row_roundtrip(db):
    job = _insert_sample(db, skills=["Python", "SQL"], status="NEW")
    row = db.conn.execute("SELECT * FROM jobs WHERE id=?", (job.id,)).fetchone()
    loaded = job_from_row(row)
    assert loaded.skills == ["Python", "SQL"]
    assert loaded.status == "NEW"


def test_count_new_since(db):
    _insert_sample(db)
    assert db.count_new_since("2000-01-01T00:00:00+00:00") == 1
    assert db.count_new_since(utcnow_iso()) == 0


def test_touch_job_ages_new_to_seen(db):
    old = "2020-01-01T00:00:00+00:00"
    job = _insert_sample(db, first_seen=old, last_seen=old)
    status = db.touch_job(job.id, new_status_days=7)
    assert status == "SEEN"


def test_touch_job_keeps_fresh_new(db):
    job = _insert_sample(db)
    status = db.touch_job(job.id, new_status_days=7)
    assert status == "NEW"


def test_mark_stale_inactive_never_deletes(db):
    old = "2020-01-01T00:00:00+00:00"
    fresh = _insert_sample(db)
    stale = _insert_sample(db, source_job_id="fx-2",
                           canonical_url="https://acme.example/j/2",
                           source_url="https://acme.example/j/2",
                           content_hash="hash-2", last_seen=old)
    changed = db.mark_stale_inactive("2026-01-01T00:00:00+00:00")
    assert changed == 1
    assert db.get_job(fresh.id).is_active is True
    assert db.get_job(stale.id).is_active is False
    assert db.count_jobs(active_only=False) == 2  # row retained


def test_scrape_run_lifecycle(db):
    run_id = db.start_run(trigger="test")
    db.finish_run(run_id, {"jobs_found": 3})
    last = db.get_last_run()
    assert last is not None and last["id"] == run_id
    assert last["counters"]["jobs_found"] == 3


def test_error_logging(db):
    db.log_error(1, source="indeed", url="https://x", error_type="MANUAL_REVIEW",
                 message="blocked", http_status=403)
    rows = db.get_errors(limit=5)
    assert len(rows) == 1
    assert rows[0]["error_type"] == "MANUAL_REVIEW"
    assert db.count_errors() == 1


def test_source_status_upsert(db):
    db.ensure_sources({"indeed": "job_board"})
    db.set_source_status("indeed", "OK", jobs_found_delta=5)
    db.set_source_status("indeed", "MANUAL_REVIEW", jobs_found_delta=2)
    row = db.get_source_rows()[0]
    assert row["status"] == "MANUAL_REVIEW"
    assert row["jobs_found"] == 7
    assert row["last_success_at"] is not None  # kept from the OK run


def test_get_stats_shape(db):
    _insert_sample(db)
    stats = db.get_stats()
    for key in ("jobs_total", "jobs_active", "jobs_new_24h", "jobs_new_7d",
                "companies", "sources", "errors", "by_status"):
        assert key in stats
    assert stats["jobs_total"] == 1
