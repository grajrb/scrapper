"""Tests for RawJob -> Job normalization. Never inventing data is critical."""
from src.models import RawJob
from src.normalization import (
    detect_remote_status,
    normalize_employment_type,
    normalize_job,
    normalize_url,
    parse_date,
    split_location,
)


def _raw(**payload):
    base = {"source_job_id": "x1", "company_name": "Acme Cloud",
            "title": "Backend Engineer", "url": "https://acme.example/j/1"}
    base.update(payload)
    return RawJob(source="greenhouse", payload=base,
                  source_url=base.get("url"))


def test_parse_date_iso_and_formats():
    assert parse_date("2026-10-04").startswith("2026-10-04")
    assert parse_date("4 Oct 2026").startswith("2026-10-04")
    assert parse_date("Oct 04, 2026").startswith("2026-10-04")
    assert parse_date(None) is None
    assert parse_date("not a date") is None


def test_split_location():
    assert split_location("Bangalore, India") == ("Bangalore", "India")
    assert split_location("Remote") == (None, None)
    assert split_location(None) == (None, None)


def test_detect_remote_status_explicit_wins():
    assert detect_remote_status("hybrid", "some remote words") == "hybrid"
    assert detect_remote_status(None, "Fully remote role") == "remote"
    assert detect_remote_status(None, "office in Bangalore") == "unknown"


def test_employment_type_normalization():
    assert normalize_employment_type("Full-time") == "full_time"
    assert normalize_employment_type("Contract") == "contract"
    assert normalize_employment_type(None) is None


def test_normalize_url_strips_tracking_and_fragment():
    a = normalize_url("https://Example.com/jobs/1?utm_source=x&fbclid=9#top")
    b = normalize_url("https://example.com/jobs/1/")
    assert a == "https://example.com/jobs/1"
    assert a == b


def test_normalize_job_fields():
    job = normalize_job(_raw(
        location="Bangalore, India",
        employment_type="Full-time",
        skills=["Python", " SQL "],
        experience_min="3",
        experience_max="5",
        posted_date="2026-10-04",
        description="Uses Python and AWS",
    ))
    assert job.title == "Backend Engineer"
    assert job.city == "Bangalore"
    assert job.country == "India"
    assert job.employment_type == "full_time"
    assert job.skills == ["Python", "SQL"]
    assert job.experience_min == 3
    assert job.posted_date.startswith("2026-10-04")
    assert job.raw_data_hash and len(job.raw_data_hash) == 64
    assert job.status == "NEW"
    assert job.is_fixture is False


def test_missing_fields_stay_none():
    job = normalize_job(_raw(location=None, description=None, skills=None,
                             salary_min=None, posted_date=None))
    assert job.location is None
    assert job.city is None
    assert job.country is None
    assert job.description is None
    assert job.skills == []
    assert job.salary_min is None
    assert job.posted_date is None
    # unknown location -> remote detection must not guess
    assert job.remote_status == "unknown"


def test_experience_swapped_values_corrected():
    job = normalize_job(_raw(experience_min=6, experience_max=2))
    assert job.experience_min == 2
    assert job.experience_max == 6


def test_fixture_source_flagged():
    job = normalize_job(RawJob(source="fixture", payload={"title": "X"}))
    assert job.is_fixture is True
