"""Tests for the common Job model and source-priority helpers."""
from src.models import (
    AdapterResult,
    Job,
    JobStatus,
    MatchLevel,
    ResultStatus,
    RunCounters,
    best_application_url,
    source_tier,
    source_type,
    SourceType,
)


def test_job_defaults_are_safe():
    job = Job()
    assert job.status == JobStatus.NEW.value
    assert job.skills == []
    assert job.match_score is None
    assert job.is_active is True
    assert job.is_fixture is False
    assert job.remote_status == "unknown"


def test_job_experience_display():
    assert Job(experience_min=2, experience_max=5).experience_display == "2-5 yrs"
    assert Job().experience_display == "Not listed"
    assert Job(experience_min=3).experience_display == "3-? yrs"


def test_source_tiers():
    assert source_tier("company_careers") == 1
    assert source_tier("generic") == 1
    assert source_tier("greenhouse") == 2
    assert source_tier("workday") == 2
    assert source_tier("indeed") == 3
    assert source_tier("unknown_board") == 3


def test_source_types():
    assert source_type("greenhouse") is SourceType.ATS
    assert source_type("naukri") is SourceType.JOB_BOARD
    assert source_type("company_careers") is SourceType.COMPANY_CAREERS


def test_application_url_priority_career_page_over_board():
    job = Job(source="indeed", source_url="https://board.example/job/1",
              canonical_url="https://ats.example/jobs/1")
    url = best_application_url(job, alternates=[("greenhouse",
                                                 "https://gh.example/j/1")])
    # official ATS link beats the job-board link
    assert url == "https://gh.example/j/1"


def test_application_url_prefers_own_official_source():
    job = Job(source="greenhouse", source_url="https://gh.example/apply/9",
              canonical_url="https://mirror.example/job/9")
    assert best_application_url(job) == "https://gh.example/apply/9"


def test_adapter_result_manual_review_flag():
    result = AdapterResult(source="indeed", status=ResultStatus.MANUAL_REVIEW,
                           reason="blocked")
    assert result.is_manual_review
    assert AdapterResult(source="x").status is ResultStatus.OK


def test_run_counters_to_dict():
    counters = RunCounters(jobs_found=10, new_jobs=4)
    data = counters.to_dict()
    assert data["jobs_found"] == 10
    assert data["new_jobs"] == 4


def test_match_level_enum_values():
    assert {m.value for m in MatchLevel} == {"FULL", "PARTIAL", "NONE", "UNKNOWN"}
