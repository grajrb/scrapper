"""Configuration loading: YAML configs + companies CSV + optional .env."""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

try:  # optional; .env is a convenience, not a requirement
    from dotenv import load_dotenv as _load_dotenv
except ImportError:  # pragma: no cover
    _load_dotenv = None

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "jobs.db"
EXPORT_DIR = DATA_DIR / "exports"
RAW_DIR = DATA_DIR / "raw"


class ConfigError(Exception):
    """Raised when a configuration file is missing or invalid."""


@dataclass
class SourceSettings:
    key: str
    enabled: bool = True
    request_delay: float = 1.5
    timeout: int = 20
    max_retries: int = 2
    backoff_factor: float = 2.0
    cache_ttl: int = 3600
    mode: Optional[str] = None          # optional search-mode override
    extra: dict[str, Any] = field(default_factory=dict)


DEFAULT_WEIGHTS = {
    "title": 30,
    "skills": 30,
    "experience": 20,
    "location": 15,
    "employment_type": 5,
}


@dataclass
class SearchConfig:
    roles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    location_aliases: dict[str, list[str]] = field(default_factory=dict)
    remote_preference: str = "any"
    experience_min: Optional[int] = None
    experience_max: Optional[int] = None
    skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=list)
    employment_types: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    minimum_match_score: int = 50
    high_match_score: int = 75
    # scoring
    weights: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    unknown_field_policy: str = "neutral"   # neutral | zero | full
    # filtering
    skill_match_mode: str = "any"           # any | all
    min_skill_matches: int = 1
    excluded_keyword_fields: list[str] = field(default_factory=lambda: ["title"])
    require_target_company: bool = True
    new_status_days: int = 7
    inactive_after_days: int = 14


@dataclass
class AppConfig:
    config_dir: Path
    companies: list[Any]                   # list[Company]
    search: SearchConfig
    sources: dict[str, SourceSettings]
    db_path: Path = DB_PATH
    export_dir: Path = EXPORT_DIR
    raw_dir: Path = RAW_DIR

    @property
    def enabled_companies(self) -> list[Any]:
        return [c for c in self.companies if c.enabled]


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Expected a mapping at the top level of {path}")
    return data


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _opt_int(value: Any, name: str) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be an integer")


def load_search_config(path: Path) -> SearchConfig:
    data = _load_yaml(path)
    scoring = data.get("scoring") or {}
    filtering = data.get("filtering") or {}

    weights = dict(DEFAULT_WEIGHTS)
    raw_weights = scoring.get("weights") or {}
    if raw_weights:
        if not isinstance(raw_weights, dict):
            raise ConfigError("scoring.weights must be a mapping")
        for key, value in raw_weights.items():
            try:
                weights[str(key)] = int(value)
            except (TypeError, ValueError):
                raise ConfigError(f"scoring.weights.{key} must be an integer")
        if sum(weights.values()) <= 0:
            raise ConfigError("scoring.weights must sum to a positive number")

    policy = str(scoring.get("unknown_field_policy", "neutral")).lower()
    if policy not in {"neutral", "zero", "full"}:
        raise ConfigError("scoring.unknown_field_policy must be neutral|zero|full")

    skill_mode = str(filtering.get("skill_match_mode", "any")).lower()
    if skill_mode not in {"any", "all"}:
        raise ConfigError("filtering.skill_match_mode must be any|all")

    remote_pref = str(data.get("remote_preference", "any")).lower()
    if remote_pref not in {"any", "prefer", "require", "onsite"}:
        raise ConfigError("remote_preference must be any|prefer|require|onsite")

    aliases_raw = data.get("location_aliases") or {}
    aliases = {str(k): _as_list(v) for k, v in aliases_raw.items()}

    return SearchConfig(
        roles=_as_list(data.get("roles")),
        locations=_as_list(data.get("locations")),
        countries=_as_list(data.get("countries")),
        location_aliases=aliases,
        remote_preference=remote_pref,
        experience_min=_opt_int(data.get("experience_min"), "experience_min"),
        experience_max=_opt_int(data.get("experience_max"), "experience_max"),
        skills=_as_list(data.get("skills")),
        preferred_skills=_as_list(data.get("preferred_skills")),
        excluded_keywords=_as_list(data.get("excluded_keywords")),
        employment_types=_as_list(data.get("employment_types")),
        industries=_as_list(data.get("industries")),
        minimum_match_score=int(data.get("minimum_match_score", 50)),
        high_match_score=int(data.get("high_match_score", 75)),
        weights=weights,
        unknown_field_policy=policy,
        skill_match_mode=skill_mode,
        min_skill_matches=int(filtering.get("min_skill_matches", 1)),
        excluded_keyword_fields=_as_list(
            filtering.get("excluded_keyword_fields") or ["title"]),
        require_target_company=bool(filtering.get("require_target_company", True)),
        new_status_days=int(filtering.get("new_status_days", 7)),
        inactive_after_days=int(filtering.get("inactive_after_days", 14)),
    )


def load_sources_config(path: Path) -> dict[str, SourceSettings]:
    data = _load_yaml(path)
    defaults = data.get("defaults") or {}
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, dict) or not raw_sources:
        raise ConfigError(f"{path} must define a non-empty 'sources' mapping")

    def _get(section: dict, key: str, fallback: Any) -> Any:
        return section[key] if key in section else fallback

    settings: dict[str, SourceSettings] = {}
    for key, value in raw_sources.items():
        value = value or {}
        if not isinstance(value, dict):
            raise ConfigError(f"sources.{key} must be a mapping")
        settings[str(key)] = SourceSettings(
            key=str(key),
            enabled=bool(_get(value, "enabled", _get(defaults, "enabled", True))),
            request_delay=float(_get(value, "request_delay",
                                     _get(defaults, "request_delay", 1.5))),
            timeout=int(_get(value, "timeout", _get(defaults, "timeout", 20))),
            max_retries=int(_get(value, "max_retries",
                                 _get(defaults, "max_retries", 2))),
            backoff_factor=float(_get(value, "backoff_factor",
                                      _get(defaults, "backoff_factor", 2.0))),
            cache_ttl=int(_get(value, "cache_ttl", _get(defaults, "cache_ttl", 3600))),
            mode=(str(value["mode"]).lower() if value.get("mode") else None),
            extra={k: v for k, v in value.items()
                   if k not in {"enabled", "request_delay", "timeout",
                                "max_retries", "backoff_factor", "cache_ttl",
                                "mode"}},
        )
    return settings


def load_companies(path: Path) -> list[Any]:
    """Load companies.csv -> list[Company]. Validates required columns."""
    from .models import Company  # local import to avoid cycles

    if not path.exists():
        raise ConfigError(f"Companies file not found: {path}")
    required = {"company_name", "company_domain", "careers_url",
                "priority", "enabled"}
    companies: list[Company] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ConfigError(f"{path} is empty")
        headers = {h.strip().lower() for h in reader.fieldnames}
        missing = required - headers
        if missing:
            raise ConfigError(
                f"{path} is missing required columns: {', '.join(sorted(missing))}")
        for line_no, row in enumerate(reader, start=2):
            row = {(k or "").strip().lower(): (v or "").strip()
                   for k, v in row.items()}
            name = row.get("company_name", "")
            if not name:
                raise ConfigError(f"{path} line {line_no}: company_name is empty")
            companies.append(Company(
                company_name=name,
                company_domain=row.get("company_domain") or None,
                careers_url=row.get("careers_url") or None,
                priority=(row.get("priority") or "B").upper(),
                enabled=str(row.get("enabled", "true")).lower()
                in {"1", "true", "yes", "y"},
            ))
    return companies


def load_app_config(config_dir: Path | None = None) -> AppConfig:
    """Load the full application configuration (companies + search + sources)."""
    cfg_dir = Path(config_dir) if config_dir else CONFIG_DIR
    if _load_dotenv is not None:
        try:
            _load_dotenv(ROOT_DIR / ".env")
        except OSError:
            pass

    companies = load_companies(cfg_dir / "companies.csv")
    search = load_search_config(cfg_dir / "search_config.yaml")
    sources = load_sources_config(cfg_dir / "sources.yaml")

    db_path = Path(os.getenv("JOB_SEARCH_DB_PATH", "") or DB_PATH)
    if not db_path.is_absolute():
        db_path = ROOT_DIR / db_path

    return AppConfig(
        config_dir=cfg_dir,
        companies=companies,
        search=search,
        sources=sources,
        db_path=db_path,
        export_dir=EXPORT_DIR,
        raw_dir=RAW_DIR,
    )



