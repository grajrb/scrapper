"""Tests for the config-driven job filter."""
from src.filtering import (
    JobFilter,
    excluded_keyword_hit,
    location_match_level,
    title_match_level,
)
from src.models import MatchLevel


def test_good_job_is_accepted(make_job, search_config):
    decision = JobFilter(search_config).evaluate(make_job())
    assert decision.accepted, decision.notes


def test_excluded_keyword_rejects(make_job, search_config):
    job = make_job(title="Director of Engineering")
    decision = JobFilter(search_config).evaluate(job)
    assert not decision.accepted
    assert "director" in decision.notes[0].lower()


def test_non_matching_title_rejected(make_job, search_config):
    job = make_job(title="Graphic Designer")
    decision = JobFilter(search_config).evaluate(job)
    assert not decision.accepted
    assert "role" in decision.notes[0].lower()


def test_wrong_location_rejected(make_job, search_config):
    job = make_job(location="Kolkata, India", city="Kolkata")
    decision = JobFilter(search_config).evaluate(job)
    assert not decision.accepted
    assert "location" in decision.notes[0].lower()


def test_location_alias_bengaluru_matches_bangalore(make_job, search_config):
    job = make_job(location="Bengaluru, India", city="Bengaluru")
    decision = JobFilter(search_config).evaluate(job)
    assert decision.accepted, decision.notes


def test_remote_job_accepted(make_job, search_config):
    job = make_job(location="Remote", city=None, country=None,
                   remote_status="remote")
    decision = JobFilter(search_config).evaluate(job)
    assert decision.accepted, decision.notes


def test_experience_out_of_range_rejected(make_job, search_config):
    job = make_job(experience_min=8, experience_max=12)
    decision = JobFilter(search_config).evaluate(job)
    assert not decision.accepted
    assert "experience" in decision.notes[0].lower()


def test_unknown_experience_accepted(make_job, search_config):
    job = make_job(experience_min=None, experience_max=None)
    decision = JobFilter(search_config).evaluate(job)
    assert decision.accepted, decision.notes


def test_wrong_employment_type_rejected(make_job, search_config):
    job = make_job(employment_type="internship")
    decision = JobFilter(search_config).evaluate(job)
    assert not decision.accepted


def test_non_target_company_rejected_by_default(make_job, search_config):
    job = make_job(target_company_match=None, match_confidence="NONE")
    decision = JobFilter(search_config).evaluate(job)
    assert not decision.accepted
    assert "target company" in decision.notes[0].lower()


def test_non_target_allowed_when_configured(make_job, search_config):
    search_config.require_target_company = False
    try:
        decision = JobFilter(search_config).evaluate(
            make_job(target_company_match=None))
        assert decision.accepted
    finally:
        search_config.require_target_company = True


def test_missing_required_skill_rejected(make_job, search_config):
    job = make_job(skills=["Go", "Rust"],
                   description="Working with Go and Rust.")
    decision = JobFilter(search_config).evaluate(job)
    assert not decision.accepted
    assert "skill" in decision.notes[0].lower()


def test_title_match_levels(search_config):
    level, role = title_match_level("Senior Backend Engineer",
                                    search_config.roles)
    assert level is MatchLevel.FULL
    level, _ = title_match_level("Sales Manager", search_config.roles)
    assert level in (MatchLevel.PARTIAL, MatchLevel.NONE)


def test_location_match_level_none_for_other_city(make_job, search_config):
    job = make_job(location="Delhi, India", city="Delhi")
    assert location_match_level(job, search_config) is MatchLevel.NONE


def test_excluded_keyword_helper(make_job, search_config):
    assert excluded_keyword_hit(make_job(title="Vice President of Sales"),
                                search_config) is not None
    assert excluded_keyword_hit(make_job(), search_config) is None
