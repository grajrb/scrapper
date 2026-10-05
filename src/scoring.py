"""Configurable 0-100 relevance scoring.

Weights come from search_config.yaml (title/skills/experience/location/
employment). Missing data is never guessed: ``unknown_field_policy``
controls whether an unknown component gets neutral (half), zero or full
credit, and always adds a warning.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import SearchConfig
from .filtering import (
    employment_match_level,
    experience_match_level,
    find_skills,
    location_match_level,
    title_match_level,
)
from .models import Job, MatchLevel, RemoteStatus

_NEUTRAL_FRACTIONS = {"neutral": 0.5, "zero": 0.0, "full": 1.0}
_PARTIAL_TITLE_FRACTION = 0.6


@dataclass
class ScoreResult:
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def score_job(job: Job, cfg: SearchConfig) -> ScoreResult:
    """Score one job 0-100 with human-readable reasons and warnings."""
    result = ScoreResult()
    neutral = _NEUTRAL_FRACTIONS.get(cfg.unknown_field_policy, 0.5)
    weights = cfg.weights
    components: list[tuple[str, int, float]] = []  # (name, weight, fraction)

    # --- title ------------------------------------------------------------
    level, role = title_match_level(job.title, cfg.roles)
    w = int(weights.get("title", 0))
    if w:
        if level is MatchLevel.FULL and role:
            components.append(("title", w, 1.0))
            result.reasons.append(f"Exact role match: {role}")
        elif level is MatchLevel.PARTIAL and role:
            components.append(("title", w, _PARTIAL_TITLE_FRACTION))
            result.reasons.append(f"Partial role match: {role}")
        elif level is MatchLevel.UNKNOWN:
            components.append(("title", w, neutral))
            result.warnings.append("Title missing")
        else:
            components.append(("title", w, 0.0))

    # --- skills -----------------------------------------------------------
    w = int(weights.get("skills", 0))
    if w and (cfg.skills or cfg.preferred_skills):
        report = find_skills(job, cfg)
        if not report.data_available and cfg.skills:
            components.append(("skills", w, neutral))
            result.warnings.append("Skills not listed")
        else:
            denom = len(cfg.skills) + 0.5 * len(cfg.preferred_skills)
            num = len(report.found) + 0.5 * len(report.preferred_found)
            components.append(("skills", w, (num / denom) if denom else 1.0))
            if report.found:
                result.reasons.append(
                    "Skills matched: " + ", ".join(report.found))
            if report.preferred_found:
                result.reasons.append(
                    "Preferred skills matched: "
                    + ", ".join(report.preferred_found))
            if cfg.skills and report.missing:
                result.warnings.append(
                    "Required skills not listed: " + ", ".join(report.missing))

    # --- experience -------------------------------------------------------
    w = int(weights.get("experience", 0))
    if w:
        level = experience_match_level(job, cfg)
        if level is MatchLevel.FULL:
            if cfg.experience_min is not None and cfg.experience_max is not None:
                range_text = f"{cfg.experience_min}-{cfg.experience_max}"
            elif cfg.experience_min is not None:
                range_text = f"{cfg.experience_min}+"
            else:
                range_text = f"up to {cfg.experience_max}"
            components.append(("experience", w, 1.0))
            result.reasons.append(
                f"Experience {job.experience_display} matches {range_text}")
        elif level is MatchLevel.UNKNOWN:
            components.append(("experience", w, neutral))
            result.warnings.append("Experience not listed")
        else:
            components.append(("experience", w, 0.0))
            result.warnings.append(
                f"Experience {job.experience_display} outside "
                f"{cfg.experience_min}-{cfg.experience_max} yrs")

    # --- location ---------------------------------------------------------
    w = int(weights.get("location", 0))
    if w:
        level = location_match_level(job, cfg)
        if level is MatchLevel.FULL:
            components.append(("location", w, 1.0))
            if job.remote_status == RemoteStatus.REMOTE.value:
                result.reasons.append("Remote role")
            else:
                result.reasons.append(f"Location match: {job.location}")
        elif level is MatchLevel.PARTIAL:
            components.append(("location", w, 0.5))
            result.reasons.append(f"Country-level location match: {job.country}")
        elif level is MatchLevel.UNKNOWN:
            components.append(("location", w, neutral))
            result.warnings.append("Location not listed")
        else:
            components.append(("location", w, 0.0))

    # --- employment type --------------------------------------------------
    w = int(weights.get("employment_type", 0))
    if w:
        level = employment_match_level(job, cfg)
        if level is MatchLevel.FULL:
            if job.employment_type:
                components.append(("employment_type", w, 1.0))
                result.reasons.append(
                    f"Employment type match: {job.employment_type}")
            else:
                components.append(("employment_type", w, neutral))
        elif level is MatchLevel.UNKNOWN:
            components.append(("employment_type", w, neutral))
            result.warnings.append("Employment type not listed")
        else:
            components.append(("employment_type", w, 0.0))

    # --- total ------------------------------------------------------------
    total_weight = sum(w for _, w, _ in components)
    if total_weight > 0:
        raw = 100.0 * sum(w * f for _, w, f in components) / total_weight
        result.score = max(0, min(100, round(raw)))
    else:
        result.score = 0

    if job.salary_min is None and job.salary_max is None:
        result.warnings.append("Salary unavailable")
    return result

