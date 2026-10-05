"""Tests for cross-source deduplication and canonical source priority."""
from src.deduplication import (
    Deduplicator,
    content_hash,
    normalize_company_name,
)


def test_normalize_company_name_strips_legal_suffixes():
    a = normalize_company_name("ABC Technologies Pvt. Ltd.")
    b = normalize_company_name("ABC Technologies")
    assert a == b == "abc technologies"
    # must NOT over-merge unrelated names
    assert normalize_company_name("ABC Tech") != a


def test_content_hash_is_deterministic(make_job):
    j1 = make_job()
    j2 = make_job(source="indeed", source_job_id="in-9",
                  source_url="https://mirror.example/job/1",
                  canonical_url="https://mirror.example/job/1")
    assert content_hash(j1) == content_hash(j2)


def test_content_hash_differs_for_different_jobs(make_job):
    base = content_hash(make_job())
    assert base != content_hash(make_job(title="Data Engineer"))
    assert base != content_hash(make_job(location="Pune, India", city="Pune"))


def test_insert_then_duplicate_by_url(db, make_job):
    dedup = Deduplicator(db)
    first = dedup.resolve(make_job())
    assert first.outcome == "new"

    # same job from another source, URL differs only by tracking params
    second_job = make_job(source="indeed", source_job_id="in-1",
                          source_url="https://acmecloud.example/careers/jobs/1?utm_source=x")
    second = dedup.resolve(second_job)
    assert second.outcome == "duplicate"
    assert second.job_id == first.job_id
    # both source references kept
    sources = {r["source"] for r in db.get_job_sources(first.job_id)}
    assert {"fixture", "indeed"} <= sources


def test_duplicate_by_content_hash_when_urls_differ(db, make_job):
    dedup = Deduplicator(db)
    first = dedup.resolve(make_job())
    other_url = make_job(source="naukri", source_job_id="nk-1",
                         source_url="https://board.example/different/path")
    second = dedup.resolve(other_url)
    assert second.outcome == "duplicate"
    assert second.job_id == first.job_id


def test_canonical_priority_promotes_career_page(db, make_job):
    dedup = Deduplicator(db)
    board_job = make_job(source="indeed", source_job_id="in-77",
                         source_url="https://board.example/job/77")
    first = dedup.resolve(board_job)
    assert db.get_job(first.job_id).source == "indeed"

    career_job = make_job(source="company_careers", source_job_id=None,
                          source_url="https://acmecloud.example/apply/77",
                          canonical_url="https://acmecloud.example/apply/77")
    second = dedup.resolve(career_job)
    assert second.outcome == "duplicate"
    assert second.promoted is True
    promoted = db.get_job(first.job_id)
    assert promoted.source == "company_careers"
    sources = {r["source"] for r in db.get_job_sources(first.job_id)}
    assert {"indeed", "company_careers"} <= sources


def test_different_jobs_stay_separate(db, make_job):
    dedup = Deduplicator(db)
    one = dedup.resolve(make_job())
    two = dedup.resolve(make_job(
        source_job_id="fx-2",
        source_url="https://acmecloud.example/j/2",
        canonical_url="https://acmecloud.example/j/2",
        title="Software Engineer"))
    assert one.outcome == "new"
    assert two.outcome == "new"
    assert one.job_id != two.job_id
