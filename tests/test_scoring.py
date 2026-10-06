"""Tests for 0-100 match scoring, reasons and warnings."""
from src.scoring import score_job


def test_strong_match_scores_high(make_job, search_config):
    # job offering every required + preferred skill from the live config
    job = make_job(title="Backend Engineer",
                   skills=list(search_config.skills),
                   description=" ".join(search_config.skills
                                        + search_config.preferred_skills),
                   employment_type="full_time")
    result = score_job(job, search_config)
    # every component matches: expect a high score with reasons
    assert result.score >= 90, (result.score, result.reasons, result.warnings)
    assert any("Exact role match" in r for r in result.reasons)
    assert any("Skills matched" in r for r in result.reasons)
    assert any("Experience" in r for r in result.reasons)
    assert any("Location match" in r for r in result.reasons)
    assert any("Salary unavailable" in w for w in result.warnings)


def test_score_is_within_bounds(make_job, search_config):
    bad = make_job(title="Janitor", skills=[], description="",
                   location="Antarctica", city=None, country=None,
                   experience_min=20, experience_max=25,
                   employment_type="part_time")
    result = score_job(bad, search_config)
    assert 0 <= result.score <= 100
    assert result.score < 50


def test_missing_skills_produce_warning_not_guess(make_job, search_config):
    job = make_job(skills=None, description=None)
    result = score_job(job, search_config)
    assert any("Skills not listed" in w for w in result.warnings)


def test_unknown_experience_neutral_policy(make_job, search_config):
    job = make_job(experience_min=None, experience_max=None)
    result = score_job(job, search_config)
    assert any("Experience not listed" in w for w in result.warnings)
    # neutral (default) policy must not zero the component
    assert result.score > 60


def test_unknown_experience_zero_policy(make_job, search_config):
    original = search_config.unknown_field_policy
    try:
        search_config.unknown_field_policy = "zero"
        job = make_job(experience_min=None, experience_max=None)
        result = score_job(job, search_config)
    finally:
        search_config.unknown_field_policy = original
    assert result.score < score_job(make_job(), search_config).score


def test_score_never_exceeds_100(make_job, search_config):
    for _ in range(5):
        job = make_job(skills=["Python", "SQL", "AWS", "Django", "FastAPI"],
                       description="Python SQL AWS Django FastAPI Docker")
        assert score_job(job, search_config).score <= 100


def test_warnings_do_not_hide_missing_salary(make_job, search_config):
    job = make_job(salary_min=None, salary_max=None)
    result = score_job(job, search_config)
    assert "Salary unavailable" in result.warnings
