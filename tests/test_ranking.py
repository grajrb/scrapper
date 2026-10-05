"""Tests for ranking: score, company priority, recency."""
from src.ranking import is_high_match, rank_jobs, select_relevant


def test_rank_by_score_desc(make_job):
    low = make_job(match_score=40, title="Low")
    high = make_job(match_score=95, title="High")
    mid = make_job(match_score=70, title="Mid")
    ranked = rank_jobs([low, high, mid])
    assert [j.title for j in ranked] == ["High", "Mid", "Low"]


def test_priority_breaks_ties(make_job):
    a_company = make_job(company_name="Acme Cloud", match_score=80)
    c_company = make_job(company_name="Zeta Co", match_score=80,
                         source_job_id="z1",
                         source_url="https://z.example/j/1")
    ranked = rank_jobs([c_company, a_company],
                       {"Acme Cloud": "A", "Zeta Co": "C"})
    assert ranked[0].company_name == "Acme Cloud"


def test_recency_breaks_tie(make_job):
    older = make_job(posted_date="2026-09-01", title="Older")
    newer = make_job(posted_date="2026-10-05", title="Newer",
                     source_job_id="n1",
                     source_url="https://acmecloud.example/careers/jobs/2")
    ranked = rank_jobs([older, newer])
    assert ranked[0].title == "Newer"


def test_unscored_jobs_sort_last(make_job):
    scored = make_job(match_score=10, title="Scored")
    unscored = make_job(title="Unscored", source_job_id="u1",
                        source_url="https://acme.example/u1")
    ranked = rank_jobs([unscored, scored])
    assert ranked[-1].title == "Unscored"


def test_select_relevant_threshold(make_job):
    jobs = [make_job(match_score=40), make_job(match_score=80)]
    assert len(select_relevant(jobs, 50)) == 1


def test_is_high_match(make_job, search_config):
    job = make_job(match_score=search_config.high_match_score)
    assert is_high_match(job, search_config.high_match_score)
    below = make_job(match_score=search_config.high_match_score - 1)
    assert not is_high_match(below, search_config.high_match_score)
