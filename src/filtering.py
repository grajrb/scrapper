"""Job filtering against config/search_config.yaml.

Pure functions expose the individual match checks (title, location,
experience, employment type, skills) so :mod:`src.scoring` can reuse them
without duplicating logic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .config import SearchConfig
from .models import Job, MatchLevel, RemoteStatus

_WS = re.compile(r"\s+")
_WORDS = re.compile(r"\w+")


def _cf(text: Optional[str]) -> str:
    return (text or "").casefold()


def _tokens(text: str) -> set[str]:
    return set(_WORDS.findall(text.casefold()))


def location_variants(cfg: SearchConfig) -> list[str]:
    """Configured locations expanded with their aliases (case-folded)."""
    lower_map = {k.casefold(): [a.casefold() for a in v]
                 for k, v in cfg.location_aliases.items()}
    out: list[str] = []
    for loc in cfg.locations:
        out.append(loc.casefold())
        out.extend(lower_map.get(loc.casefold(), []))
    return list(dict.fromkeys(out))


def title_match_level(title: Optional[str],
                      roles: list[str]) -> tuple[MatchLevel, Optional[str]]:
    """FULL = a whole role phrase appears; PARTIAL = >=50% token overlap."""
    if not roles:
        return MatchLevel.FULL, None
    title_cf = _cf(title)
    if not title_cf:
        return MatchLevel.UNKNOWN, None
    title_tokens = _tokens(title_cf)
    best_level, best_role = MatchLevel.NONE, None
    for role in roles:
        role_cf = _cf(role)
        if not role_cf:
            continue
        if role_cf in title_cf:
            return MatchLevel.FULL, role
        role_tokens = _tokens(role_cf)
        if role_tokens and title_tokens:
            overlap = len(role_tokens & title_tokens) / len(role_tokens)
            if overlap >= 0.5 and best_level is not MatchLevel.FULL:
                best_level, best_role = MatchLevel.PARTIAL, role
    return best_level, best_role


def location_match_level(job: Job, cfg: SearchConfig) -> MatchLevel:
    if not cfg.locations and not cfg.countries:
        return MatchLevel.FULL
    variants = location_variants(cfg)
    non_remote = [v for v in variants if v != "remote"]
    hay = " ".join(x for x in (_cf(job.location), _cf(job.city)) if x)
    is_remote = job.remote_status == RemoteStatus.REMOTE.value

    for variant in non_remote:
        if variant and variant in hay:
            return MatchLevel.FULL

    if is_remote or "remote" in hay:
        if cfg.remote_preference == "onsite":
            return MatchLevel.NONE
        return MatchLevel.FULL if ("remote" in variants
                                   or cfg.remote_preference != "onsite") \
            else MatchLevel.PARTIAL

    if not hay:
        return MatchLevel.UNKNOWN
    if cfg.countries and job.country:
        for country in cfg.countries:
            if _cf(country) in _cf(job.country) or _cf(job.country) in _cf(country):
                return MatchLevel.PARTIAL
    if cfg.countries and not job.country:
        return MatchLevel.UNKNOWN
    return MatchLevel.NONE


def experience_match_level(job: Job, cfg: SearchConfig) -> MatchLevel:
    if job.experience_min is None and job.experience_max is None:
        return MatchLevel.UNKNOWN
    if cfg.experience_min is None and cfg.experience_max is None:
        return MatchLevel.FULL
    jmin = job.experience_min if job.experience_min is not None else float("-inf")
    jmax = job.experience_max if job.experience_max is not None else float("inf")
    cmin = cfg.experience_min if cfg.experience_min is not None else float("-inf")
    cmax = cfg.experience_max if cfg.experience_max is not None else float("inf")
    return MatchLevel.FULL if jmin <= cmax and jmax >= cmin else MatchLevel.NONE


def employment_match_level(job: Job, cfg: SearchConfig) -> MatchLevel:
    if not cfg.employment_types:
        return MatchLevel.FULL
    if not job.employment_type:
        return MatchLevel.UNKNOWN
    wanted = {_cf(e) for e in cfg.employment_types}
    return MatchLevel.FULL if _cf(job.employment_type) in wanted else MatchLevel.NONE


@dataclass
class SkillReport:
    found: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    preferred_found: list[str] = field(default_factory=list)
    data_available: bool = True   # False = no skills list and no description


def _skill_in_text(skill: str, text: str) -> bool:
    if not text:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(skill.casefold()) + r"(?![a-z0-9])"
    return re.search(pattern, text.casefold()) is not None


def find_skills(job: Job, cfg: SearchConfig) -> SkillReport:
    skills_cf = [_cf(s) for s in (job.skills or [])]
    description = job.description or ""
    report = SkillReport(data_available=bool(job.skills) or bool(description))

    def _present(skill: str) -> bool:
        return _cf(skill) in skills_cf or _skill_in_text(skill, description)

    for skill in cfg.skills:
        (report.found if _present(skill) else report.missing).append(skill)
    for skill in cfg.preferred_skills:
        if _present(skill):
            report.preferred_found.append(skill)
    return report


def excluded_keyword_hit(job: Job, cfg: SearchConfig) -> Optional[str]:
    fields = cfg.excluded_keyword_fields or ["title"]
    texts = []
    for name in fields:
        if name == "title":
            texts.append(_cf(job.title))
        elif name == "description":
            texts.append(_cf(job.description))
    blob = "\n".join(t for t in texts if t)
    if not blob:
        return None
    for keyword in cfg.excluded_keywords:
        if keyword.casefold() in blob:
            return keyword
    return None


@dataclass
class FilterDecision:
    accepted: bool
    notes: list[str] = field(default_factory=list)

    @property
    def reason(self) -> Optional[str]:
        return self.notes[0] if self.notes and not self.accepted else None


class JobFilter:
    """Config-driven pass/fail filter. Runs BEFORE scoring."""

    def __init__(self, cfg: SearchConfig):
        self.cfg = cfg

    def evaluate(self, job: Job) -> FilterDecision:
        cfg = self.cfg
        notes: list[str] = []

        if cfg.require_target_company and not job.target_company_match:
            return FilterDecision(False, ["Not a target company"])

        hit = excluded_keyword_hit(job, cfg)
        if hit:
            return FilterDecision(False, [f"Excluded keyword: {hit}"])

        if cfg.roles:
            level, role = title_match_level(job.title, cfg.roles)
            if level is MatchLevel.NONE:
                return FilterDecision(
                    False, [f"No role match for '{job.title}'"])
            if level is MatchLevel.FULL and role:
                notes.append(f"Role match: {role}")
            elif level is MatchLevel.PARTIAL and role:
                notes.append(f"Partial role match: {role}")
            elif level is MatchLevel.UNKNOWN:
                notes.append("Title missing - role not verified")

        level = location_match_level(job, cfg)
        if level is MatchLevel.NONE:
            return FilterDecision(
                False, [f"Location not in list: {job.location or 'unknown'}"])
        if level is MatchLevel.FULL:
            notes.append(f"Location match: {job.location or 'remote'}")
        elif level is MatchLevel.UNKNOWN:
            notes.append("Location not listed")

        level = experience_match_level(job, cfg)
        if level is MatchLevel.NONE:
            return FilterDecision(
                False, [f"Experience {job.experience_display} outside "
                        f"{cfg.experience_min}-{cfg.experience_max} yrs"])
        if level is MatchLevel.FULL:
            notes.append(f"Experience match: {job.experience_display}")
        elif level is MatchLevel.UNKNOWN:
            notes.append("Experience not listed")

        level = employment_match_level(job, cfg)
        if level is MatchLevel.NONE:
            return FilterDecision(
                False, [f"Employment type not wanted: {job.employment_type}"])
        if level is MatchLevel.FULL and job.employment_type:
            notes.append(f"Employment type match: {job.employment_type}")

        if cfg.skills or cfg.preferred_skills:
            report = find_skills(job, cfg)
            if cfg.skills:
                if cfg.skill_match_mode == "all" and report.missing:
                    return FilterDecision(
                        False, ["Missing required skills: "
                                + ", ".join(report.missing)])
                if cfg.skill_match_mode == "any" and len(report.found) < cfg.min_skill_matches:
                    if not report.data_available:
                        notes.append("Skills not listed")
                    else:
                        return FilterDecision(
                            False, [f"Only {len(report.found)}/{cfg.min_skill_matches} "
                                    f"required skills matched"])
                if report.found:
                    notes.append("Skills matched: " + ", ".join(report.found))

        return FilterDecision(True, notes)


