"""Shared pytest fixtures. All tests are offline (no live websites)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_app_config  # noqa: E402
from src.database import Database  # noqa: E402
from src.models import Job  # noqa: E402


@pytest.fixture(scope="session")
def app_config():
    """The real project configuration (config/*.yaml + companies.csv)."""
    return load_app_config()


@pytest.fixture()
def search_config(app_config):
    return app_config.search


@pytest.fixture()
def db(tmp_path):
    """Fresh SQLite database per test."""
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture()
def make_job(search_config):
    """Factory for normalized Job objects.

    Defaults follow the live search_config so tests stay consistent with
    whatever roles/skills/locations are configured.
    """
    def _make(**overrides) -> Job:
        defaults = dict(
            company_name="Acme Cloud",
            source="fixture",
            source_job_id="fx-1",
            title="Backend Engineer",
            source_url="https://acmecloud.example/careers/jobs/1",
            canonical_url="https://acmecloud.example/careers/jobs/1",
            location="Bangalore, India",
            city="Bangalore",
            country="India",
            remote_status="onsite",
            employment_type="full_time",
            experience_min=3,
            experience_max=5,
            skills=list(search_config.skills),
            description="Build APIs with Python, Node.js, SQL and Azure.",
            posted_date="2026-10-01",
            target_company_match="Acme Cloud",
            match_confidence="HIGH",
        )
        defaults.update(overrides)
        return Job(**defaults)

    return _make
