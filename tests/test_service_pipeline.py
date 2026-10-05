"""End-to-end pipeline tests using the local fixture source (no network).

Verifies: normalize -> target match -> dedup -> store -> filter -> score,
run-over-run new-job tracking, MANUAL_REVIEW handling, and honest
NOT_AVAILABLE reporting for sources without adapters.
"""
from src.services.job_service import JobService


def test_first_fixture_run_counts(db, app_config):
    service = JobService(app_config, db)
    counters, duration = service.run(sources=["fixture"])

    assert duration >= 0
    assert counters.jobs_found == 14          # raw records in fixture file
    assert counters.new_jobs == 12            # 2 records are duplicates
    assert counters.duplicates == 2
    assert counters.filtered_out == 6         # keyword/location/skills/etc.
    assert counters.high_match >= 1
    assert counters.errors == 0
    assert counters.manual_review == 0

    stats = db.get_stats()
    assert stats["jobs_total"] == 12
    assert stats["job_source_refs"] == 14     # 12 canonical + 2 mirror refs


def test_second_run_detects_no_new_jobs(db, app_config):
    service = JobService(app_config, db)
    service.run(sources=["fixture"])
    counters, _ = service.run(sources=["fixture"])
    assert counters.new_jobs == 0
    assert counters.duplicates == 14
    assert db.get_stats()["jobs_total"] == 12


def test_cross_source_references_kept(db, app_config):
    service = JobService(app_config, db)
    service.run(sources=["fixture"])
    job = next(j for j in db.list_jobs()
               if j.source_job_id == "fx-1001")
    refs = {r["source"] for r in db.get_job_sources(job.id)}
    assert {"fixture", "fixture_web"} <= refs


def test_non_target_company_is_not_matched(db, app_config):
    service = JobService(app_config, db)
    service.run(sources=["fixture"])
    zenith = [j for j in db.list_jobs(active_only=False)
              if j.company_name == "Zenith Systems"]
    assert zenith, "fixture job should still be stored for auditing"
    assert zenith[0].target_company_match is None
    assert zenith[0].match_score is None      # rejected by target filter


def test_jobs_marked_as_fixture(db, app_config):
    service = JobService(app_config, db)
    service.run(sources=["fixture"])
    assert all(j.is_fixture for j in db.list_jobs())


def test_source_without_adapter_reports_not_available(db, app_config):
    service = JobService(app_config, db)
    counters, _ = service.run(sources=["greenhouse"])
    assert counters.sources_processed == 0
    row = db.get_source_row("greenhouse")
    assert row is not None and row["status"] == "NOT_AVAILABLE"


def test_generic_source_yields_manual_review(db, app_config):
    service = JobService(app_config, db)
    counters, _ = service.run(sources=["generic"])
    assert counters.manual_review == len(app_config.enabled_companies)
    assert counters.errors == 0
    errors = db.get_errors(limit=50)
    assert errors and all(e["error_type"] == "MANUAL_REVIEW" for e in errors)
    row = db.get_source_row("generic")
    assert row["status"] == "MANUAL_REVIEW"


def test_run_is_recorded(db, app_config):
    service = JobService(app_config, db)
    service.run(sources=["fixture"])
    last = db.get_last_run()
    assert last is not None
    assert last["status"] == "COMPLETED"
    assert last["counters"]["new_jobs"] == 12
